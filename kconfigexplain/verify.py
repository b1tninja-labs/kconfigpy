"""Compare what was asked for with what the kernel's own ``conf`` actually kept."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from kconfigexplain.kconfig import And, Const, Expr, KconfigDb, Not, Or, Sym, Unknown

_SET = re.compile(r"^CONFIG_([A-Za-z0-9_]+)=(.*)$")


def read_config(path: Path) -> dict[str, str]:
    """Read a ``.config`` or fragment as ``{symbol: value}``, omitting unset options."""
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _SET.match(line)
        if match is not None:
            values[match.group(1)] = match.group(2)
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
        if symbol in resolved:
            kept.append(symbol)
            continue
        definition = db.preferred(symbol)
        failing = (
            [] if definition is None else [render(d) for d in definition.all_deps() if holds(d, resolved) is False]
        )
        dropped[symbol] = failing
    return Verification(kept, dropped)
