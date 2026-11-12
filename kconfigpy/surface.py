"""Attack-surface report: which enabled options bring which code, and which banned options are on.

The banned list is an input, never a list of this module's own. The firmware keeps it in
``kernel/banned.list``; ``read_banned`` reads whatever file it is given. A config is a resolved
``.config`` or a fragment, read with ``kconfigpy.verify.read_config``: a fragment is judged on
what it asks for, a ``.config`` on what the kernel kept. Code is attributed through the module
map from ``kconfigpy.kbuild.module_map``. An enabled option with no mapping is reported as
unmapped, never guessed at.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

_OPTION = re.compile(r"[A-Za-z0-9_]+")


def read_banned(path: Path) -> list[str]:
    """Read a banned list: one option per line, with ``#`` comments and blank lines ignored.

    A ``CONFIG_`` prefix is accepted and stripped, and a repeated name is listed once. A line that
    is not a single option name is refused with its line number, so an entry is never skipped
    silently.
    """
    names: list[str] = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        name = line.removeprefix("CONFIG_")
        if not _OPTION.fullmatch(name):
            raise ValueError(f"{path}:{number}: {line!r} is not one option name")
        if name not in names:
            names.append(name)
    return names


@dataclass
class Surface:
    """What an enabled config brings, and which banned options it turns on."""

    enabled: dict[str, str] = field(default_factory=dict)  # every option set to y or m, to its value
    code: dict[str, list[str]] = field(default_factory=dict)  # enabled option -> modules it builds
    unmapped: list[str] = field(default_factory=list)  # enabled options with no module mapping
    banned: dict[str, str] = field(default_factory=dict)  # banned options that are enabled, to their value


def surface(config: dict[str, str], modules: dict[str, set[str]], banned: Iterable[str]) -> Surface:
    """Report the code each enabled option brings and the banned options that are enabled.

    ``config`` is ``{symbol: value}`` from a resolved ``.config`` or a fragment; a value of ``n``
    is off, and an option absent from it is off. ``modules`` is ``{module: {symbols}}`` as
    ``kconfigpy.kbuild.module_map`` returns it. ``banned`` is the list from ``read_banned``.
    """
    enabled = {symbol: value for symbol, value in config.items() if value != "n"}
    modules_of: dict[str, list[str]] = {}
    for module, symbols in modules.items():
        for symbol in symbols:
            modules_of.setdefault(symbol, []).append(module)
    report = Surface(enabled=dict(sorted(enabled.items())))
    for symbol in report.enabled:
        if symbol in modules_of:
            report.code[symbol] = sorted(modules_of[symbol])
        else:
            report.unmapped.append(symbol)
    report.banned = {symbol: enabled[symbol] for symbol in dict.fromkeys(banned) if symbol in enabled}
    return report


def report_text(result: Surface) -> str:
    """Render the surface as Markdown: banned options first, then the code each option brings."""
    lines = ["# Attack-surface report", "", "## Banned options enabled"]
    lines += [f"- `{symbol}={value}`" for symbol, value in result.banned.items()] or ["- none"]
    lines += ["", "## Code brought by enabled options"]
    lines += [f"- `{symbol}`: {', '.join(modules)}" for symbol, modules in result.code.items()] or ["- none"]
    lines += ["", "## Enabled options with no module mapping (unknown, not guessed)"]
    lines += [f"- `{symbol}`" for symbol in result.unmapped] or ["- none"]
    return "\n".join(lines) + "\n"
