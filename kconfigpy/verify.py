"""Compare what was asked for with what the kernel's own ``conf`` actually kept."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from kconfigpy.kconfig import And, Const, Expr, KconfigDb, Not, Or, Sym, Unknown

_SET = re.compile(r"^CONFIG_([A-Za-z0-9_]+)=(.*)$")
_UNSET = re.compile(r"^# CONFIG_([A-Za-z0-9_]+) is not set$")


def read_config(path: Path) -> dict[str, str]:
    """Read a ``.config`` or fragment as ``{symbol: value}``, omitting unset options."""
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _SET.match(line)
        if match is not None:
            values[match.group(1)] = match.group(2)
    return values


def read_exact(path: Path) -> dict[str, str]:
    """Like :func:`read_config`, but a ``# CONFIG_X is not set`` line is the explicit value ``n``."""
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _SET.match(line)
        if match is not None:
            values[match.group(1)] = match.group(2)
            continue
        unset = _UNSET.match(line)
        if unset is not None:
            values[unset.group(1)] = "n"
    return values


def holds(expr: Expr, config: dict[str, str]) -> bool | None:
    """Evaluate against a resolved config; ``None`` when this reader cannot tell."""
    if isinstance(expr, Sym):
        return expr.name in config
    if isinstance(expr, Const):
        return expr.value != "n"
    if isinstance(expr, Unknown):
        return None
    if isinstance(expr, Not):
        inner = holds(expr.term, config)
        return None if inner is None else not inner
    left, right = holds(expr.left, config), holds(expr.right, config)
    if isinstance(expr, And):
        if left is False or right is False:
            return False
        return None if left is None or right is None else True
    assert isinstance(expr, Or)
    if left or right:
        return True
    return None if left is None or right is None else False


def render(expr: Expr) -> str:
    if isinstance(expr, Sym):
        return expr.name
    if isinstance(expr, Const):
        return expr.value
    if isinstance(expr, Unknown):
        return expr.text
    if isinstance(expr, Not):
        return f"!{render(expr.term)}"
    joiner = "&&" if isinstance(expr, And) else "||"
    return f"({render(expr.left)} {joiner} {render(expr.right)})"


@dataclass
class Verification:
    kept: list[str]
    dropped: dict[str, list[str]]  # symbol -> dependency terms that do not hold


def verify(requested: dict[str, str], resolved: dict[str, str], db: KconfigDb) -> Verification:
    kept: list[str] = []
    dropped: dict[str, list[str]] = {}
    for symbol in sorted(requested):
        want = requested[symbol]
        if want == "n":
            # A disable line is met by an explicit "not set" or by absence, never by any value.
            got = resolved.get(symbol, "n")
            if got == "n":
                kept.append(symbol)
            else:
                dropped[symbol] = [f"resolved as {got}, requested n"]
            continue
        if symbol in resolved:
            got = resolved[symbol]
            if got == want:
                kept.append(symbol)
            else:
                dropped[symbol] = [f"resolved as {got}, requested {want}"]
            continue
        definition = db.preferred(symbol)
        failing = (
            [] if definition is None else [render(d) for d in definition.all_deps() if holds(d, resolved) is False]
        )
        dropped[symbol] = failing
    return Verification(kept, dropped)
