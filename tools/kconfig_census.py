"""Count what a kernel tree's Kconfig files actually use, and what the reader could not evaluate.

docs/kconfig-coverage.md quotes these numbers. Run it again when the pinned kernel changes:

    python tools/kconfig_census.py --tree /path/to/linux-6.18.62 --arch x86

It reads every Kconfig file the reader reached for that architecture. The statement counts are a plain
scan of those files (help text skipped), so they do not depend on the reader being right.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kconfigpy.kconfig import And, Expr, Not, Or, Unknown, read_kconfig

ENTRIES = ("config", "menuconfig", "choice", "comment", "menu", "if", "source", "mainmenu")
ATTRIBUTES = (
    *("bool", "tristate", "string", "hex", "int", "def_bool", "def_tristate"),
    *("prompt", "default", "depends", "select", "imply", "visible", "range", "help", "modules", "transitional"),
)
CONDITIONAL = ("select", "imply", "default", "def_bool", "def_tristate", "range", "prompt", "bool", "tristate")


def _indent(line: str) -> int:
    expanded = line.expandtabs(8)
    return len(expanded) - len(expanded.lstrip())


def scan(path: Path, counts: Counter[str]) -> None:
    """Count statements in one file. Help bodies are skipped by indentation, as the kernel's lexer does."""
    help_indent: int | None = None
    in_help = False
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if in_help:
            if not line:
                continue
            if help_indent is None:
                help_indent = _indent(raw)
            if help_indent > 0 and _indent(raw) >= help_indent:
                continue
            in_help = False
        if not line or line.startswith("#"):
            continue
        word = line.split()[0]
        if word in ENTRIES or word in ATTRIBUTES:
            counts[word] += 1
            if word in CONDITIONAL and re.search(r"\bif\b", line):
                counts[f"{word} ... if"] += 1
            if word == "help":
                in_help, help_indent = True, None
        elif re.match(r"[\w-]+\s*(:=|\+=|=)", line):
            counts["macro assignment"] += 1


def classify(expr: Expr, counts: Counter[str]) -> None:
    counts["expression terms"] += 1
    if isinstance(expr, Unknown):
        if "$(" in expr.text:
            counts["unknown: macro call"] += 1
        elif re.search(r"[<>]", expr.text):
            counts["unknown: ordered comparison"] += 1
        else:
            counts["unknown: equality that is not against y/m/n"] += 1
    elif isinstance(expr, And | Or):
        classify(expr.left, counts)
        classify(expr.right, counts)
    elif isinstance(expr, Not):
        classify(expr.term, counts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tree", type=Path, required=True)
    parser.add_argument("--arch", default="x86")
    args = parser.parse_args(argv)
    db = read_kconfig(args.tree, args.arch)
    definitions = [d for found in db.definitions.values() for d in found]
    if not definitions:
        raise SystemExit(f"{args.tree}: no Kconfig symbols read; is this a kernel tree?")
    counts: Counter[str] = Counter()
    files = sorted({d.file for d in definitions} | {"Kconfig"})
    for name in files:
        scan(args.tree / name, counts)
    for definition in definitions:
        for expr in definition.all_deps():
            classify(expr, counts)
    counts["symbols"] = len(db.definitions)
    counts["definitions"] = len(definitions)
    counts["symbols defined more than once"] = sum(len(found) > 1 for found in db.definitions.values())
    counts["files"] = len(files)
    counts["missing sources"] = len(db.missing_sources)
    counts["parse errors"] = len(db.errors)
    for kind, number in sorted(Counter(d.kind or "(untyped)" for d in definitions).items()):
        counts[f"type: {kind}"] = number
    for key in sorted(counts):
        print(f"{counts[key]:>8}  {key}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
