"""Compare what was asked for with what the kernel's own ``conf`` actually kept."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
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
        return config.get(expr.name, "n") != "n"
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
class Changed:
    requested: str
    resolved: str
    blocking: list[str]


@dataclass
class Verification:
    """What ``conf`` did to each requested line.

    ``dropped``: absent from the resolved config (symbol unknown to this tree/arch, or never written).
    ``changed``: present with a different value (``y`` became ``m``, an int was clamped, ``n`` became ``y``).
    ``disabled``: written as ``# CONFIG_X is not set`` although something else was requested.
    Each of the last three carries the dependency terms that do not hold, where the reader can name them.
    """

    kept: list[str]
    dropped: dict[str, list[str]] = field(default_factory=dict)
    changed: dict[str, Changed] = field(default_factory=dict)
    disabled: dict[str, list[str]] = field(default_factory=dict)

    @property
    def failed(self) -> bool:
        return bool(self.dropped or self.changed or self.disabled)


def _failing(symbol: str, resolved: dict[str, str], db: KconfigDb) -> list[str]:
    definition = db.preferred(symbol)
    if definition is None:
        return []
    return [render(d) for d in definition.all_deps() if holds(d, resolved) is False]


def verify(requested: dict[str, str], resolved: dict[str, str], db: KconfigDb) -> Verification:
    """Compare each requested line verbatim with the resolved config.

    Use :func:`read_exact` for ``resolved`` to tell an explicit "not set" (disabled) from an absent
    symbol (dropped); with :func:`read_config` every "not set" line reads as absent.
    """
    result = Verification(kept=[])
    for symbol in sorted(requested):
        want = requested[symbol]
        got = resolved.get(symbol)
        if want == "n":
            # A disable line is met by an explicit "not set" or by absence, never by any value.
            if got is None or got == "n":
                result.kept.append(symbol)
            else:
                result.changed[symbol] = Changed(want, got, _failing(symbol, resolved, db))
        elif got == want:
            result.kept.append(symbol)
        elif got is None:
            result.dropped[symbol] = _failing(symbol, resolved, db)
        elif got == "n":
            result.disabled[symbol] = _failing(symbol, resolved, db)
        else:
            result.changed[symbol] = Changed(want, got, _failing(symbol, resolved, db))
    return result


def report(result: Verification) -> list[str]:
    """One line per problem, grouped by outcome; empty when everything was kept."""

    def why(blocking: list[str]) -> str:
        return ", ".join(blocking) or "no failing dependency found"

    lines = [f"  dropped {s}: {why(b)}" for s, b in result.dropped.items()]
    lines += [
        f"  changed {s}: requested {c.requested}, resolved {c.resolved}; {why(c.blocking)}"
        for s, c in result.changed.items()
    ]
    lines += [f"  disabled {s}: {why(b)}" for s, b in result.disabled.items()]
    return lines
