"""A deliberately small Kconfig reader: symbols, prompts, dependencies and selects.

It extracts the dependency graph and nothing else. The kernel's own ``conf`` remains the
authority on what a configuration resolves to; ``kconfigexplain.verify`` asks it.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Sym:
    name: str


@dataclass(frozen=True)
class Const:
    value: str  # y, m or n


@dataclass(frozen=True)
class Not:
    term: Expr


@dataclass(frozen=True)
class And:
    left: Expr
    right: Expr


@dataclass(frozen=True)
class Or:
    left: Expr
    right: Expr


@dataclass(frozen=True)
class Unknown:
    """A term this reader cannot evaluate, such as a compiler probe or a numeric test."""

    text: str


Expr = Sym | Const | Not | And | Or | Unknown

_TOKEN = re.compile(
    r"""\$\((?:[^()]|\((?:[^()]|\([^()]*\))*\))*\)|"[^"]*"|'[^']*'|&&|\|\||!=|<=|>=|=|<|>|!|\(|\)|[A-Za-z0-9_.\-/+]+"""
)


class _ExprParser:
    def __init__(self, text: str) -> None:
        self.tokens = _TOKEN.findall(text)
        self.pos = 0

    def peek(self) -> str | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def take(self) -> str:
        token: str = self.tokens[self.pos]
        self.pos += 1
        return token

    def parse_or(self) -> Expr:
        left = self.parse_and()
        while self.peek() == "||":
            self.take()
            left = Or(left, self.parse_and())
        return left

    def parse_and(self) -> Expr:
        left = self.parse_unary()
        while self.peek() == "&&":
            self.take()
            left = And(left, self.parse_unary())
        return left

    def parse_unary(self) -> Expr:
        token = self.peek()
        if token == "!":
            self.take()
            return Not(self.parse_unary())
        if token == "(":
            self.take()
            inner = self.parse_or()
            if self.peek() == ")":
                self.take()
            return inner
        return self.parse_atom()

    def parse_atom(self) -> Expr:
        left = self.take()
        if self.peek() in {"=", "!=", "<", ">", "<=", ">="}:
            operator = self.take()
            right = self.take() if self.peek() is not None else ""
            return _comparison(left, operator, right)
        return _atom(left)


def _unquote(token: str) -> str:
    return token[1:-1] if len(token) >= 2 and token[0] in "\"'" and token[-1] == token[0] else token


def _atom(token: str) -> Expr:
    if token in {"y", "m", "n"}:
        return Const(token)
    if token.startswith("$(") or token[0] in "\"'":
        return Unknown(token)
    return Sym(token)


def _comparison(left: str, operator: str, right: str) -> Expr:
    value = _unquote(right)
    if operator in {"=", "!="} and value in {"y", "m", "n"} and re.fullmatch(r"[A-Za-z0-9_]+", left):
        positive = (operator == "=") == (value != "n")
        return Sym(left) if positive else Not(Sym(left))
    return Unknown(f"{left} {operator} {right}")


def parse_expr(text: str) -> Expr:
    """Parse one dependency expression; anything unparseable becomes ``Unknown``."""
    parser = _ExprParser(text)
    if not parser.tokens:
        return Unknown(text)
    try:
        return parser.parse_or()
    except IndexError:
        return Unknown(text)


@dataclass
class _Block:
    deps: list[Expr] = field(default_factory=list)


@dataclass
class Definition:
    name: str
    file: str
    line: int
    kind: str = ""
    has_prompt: bool = False
    has_default: bool = False
    deps: list[Expr] = field(default_factory=list)
    selects: list[str] = field(default_factory=list)
    blocks: list[_Block] = field(default_factory=list)
    prompt_condition: Expr | None = None

    def all_deps(self) -> Iterator[Expr]:
        yield from self.deps
        for block in self.blocks:
            yield from block.deps
        if self.prompt_condition is not None and not self.has_default:
            yield self.prompt_condition


@dataclass
class KconfigDb:
    definitions: dict[str, list[Definition]] = field(default_factory=dict)
    missing_sources: list[str] = field(default_factory=list)

    def has_prompt(self, name: str) -> bool:
        return any(d.has_prompt for d in self.definitions.get(name, []))

    def is_settable(self, name: str) -> bool:
        return any(d.has_prompt and d.kind in {"bool", "tristate"} for d in self.definitions.get(name, []))

    def preferred(self, name: str) -> Definition | None:
        found = self.definitions.get(name, [])
        return next((d for d in found if d.has_prompt), found[0] if found else None)


_TYPES = {"bool", "tristate", "string", "hex", "int", "def_bool", "def_tristate"}
_HELP = {"help", "---help---"}


def _split_condition(rest: str) -> tuple[str, str | None]:
    """Split ``"prompt text" if COND`` or ``VALUE if COND`` on the top-level ``if``."""
    match = re.match(r"""\s*("[^"]*"|'[^']*'|\S+)?\s*(?:\bif\b\s*(.*))?$""", rest)
    if match is None:
        return rest.strip(), None
    return (match.group(1) or "").strip(), match.group(2)


class _Parser:
    def __init__(self, tree: Path, arch: str) -> None:
        self.tree = tree
        self.variables = {"SRCARCH": arch, "ARCH": arch, "HEADER_ARCH": arch, "srctree": "."}
        self.db = KconfigDb()
        self.blocks: list[_Block] = []
        self.target: Definition | _Block | None = None
        self.seen: set[Path] = set()

    def expand(self, text: str) -> str:
        return re.sub(r"\$\((\w+)\)", lambda m: self.variables.get(m.group(1), m.group(0)), text)

    def parse_file(self, relative: str) -> None:
        path = self.tree / relative
        if not path.is_file():
            self.db.missing_sources.append(relative)
            return
        resolved = path.resolve()
        if resolved in self.seen:
            return
        self.seen.add(resolved)
        self.parse_lines(path.read_text(encoding="utf-8", errors="replace").splitlines(), relative)

    def parse_lines(self, lines: list[str], relative: str) -> None:
        index = 0
        while index < len(lines):
            number = index + 1
            raw = lines[index]
            index += 1
            while raw.endswith("\\") and index < len(lines):
                raw = raw[:-1] + " " + lines[index]
                index += 1
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            word, _, rest = line.partition(" ") if " " in line and "\t" not in line.split(" ")[0] else _split_tab(line)
            rest = rest.strip()
            if word in _HELP or (word == "help" and not rest):
                index = _skip_help(lines, index)
                self.target = self.target if isinstance(self.target, Definition) else None
                continue
            self.statement(word, rest, relative, number)

    def statement(self, word: str, rest: str, relative: str, number: int) -> None:
        if word in {"config", "menuconfig"}:
            definition = Definition(rest.split()[0], relative, number, blocks=list(self.blocks))
            self.db.definitions.setdefault(definition.name, []).append(definition)
            self.target = definition
        elif word == "source":
            self.target = None
            self.parse_file(self.expand(_unquote(rest.split()[0])))
        elif word in {"menu", "choice"}:
            block = _Block()
            self.blocks.append(block)
            self.target = block
        elif word == "if":
            self.blocks.append(_Block([parse_expr(rest)]))
            self.target = None
        elif word in {"endmenu", "endchoice", "endif"}:
            if self.blocks:
                self.blocks.pop()
            self.target = None
        elif word == "comment" or word == "mainmenu":
            self.target = None
        elif word == "depends" and self.target is not None:
            self.target.deps.append(parse_expr(rest.removeprefix("on").strip()))
        elif isinstance(self.target, Definition):
            self.attribute(self.target, word, rest)

    @staticmethod
    def attribute(target: Definition, word: str, rest: str) -> None:
        if word in _TYPES:
            target.kind = word.removeprefix("def_")
            if word.startswith("def_"):
                target.has_default = True
                return
            prompt, condition = _split_condition(rest)
            if prompt:
                target.has_prompt = True
                if condition:
                    target.prompt_condition = parse_expr(condition)
        elif word == "prompt":
            target.has_prompt = True
            _, condition = _split_condition(rest)
            if condition:
                target.prompt_condition = parse_expr(condition)
        elif word == "default":
            target.has_default = True
        elif word == "select":
            target.selects.append(rest.split()[0])


def _split_tab(line: str) -> tuple[str, str, str]:
    parts = line.split(None, 1)
    return parts[0], " ", parts[1] if len(parts) > 1 else ""


def _indent(line: str) -> int:
    return len(line.expandtabs(8)) - len(line.expandtabs(8).lstrip())


def _skip_help(lines: list[str], index: int) -> int:
    help_indent: int | None = None
    while index < len(lines):
        line = lines[index]
        if line.strip():
            current = _indent(line)
            if help_indent is None:
                if current == 0:
                    return index
                help_indent = current
            elif current < help_indent:
                return index
        index += 1
    return index


def read_kconfig(tree: Path, arch: str = "x86", entry: str = "Kconfig") -> KconfigDb:
    """Read the whole Kconfig graph for one architecture from a kernel tree."""
    parser = _Parser(tree, arch)
    parser.parse_file(entry)
    return parser.db
