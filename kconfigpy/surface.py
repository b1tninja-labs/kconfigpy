"""Attack-surface report: which enabled options bring which code, and which banned options are on.

The authority is the resolved ``.config``: it is what the kernel's own ``conf`` kept, so an option
that a ``default y`` or an ``imply`` turned on is in it even though no fragment named it. A
fragment is what was asked for; ``requested_by`` takes its enabled names, and ``surface`` lists
what the resolved config enables beyond them as ``unrequested``.

Two lists are cross-checked against the enabled set: the banned list (options that must not be on)
and the exclude list (options deliberately left out of the fragment). Both are inputs read from
files, never lists of this module's own. Code is attributed through the module map from
``kconfigpy.kbuild.module_map``; an enabled option with no mapping is reported as unmapped, never
guessed at.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

_OPTION = re.compile(r"[A-Za-z0-9_]+")


def read_option_list(path: Path) -> list[str]:
    """Read an option list: one option per line, with ``#`` comments and blank lines ignored.

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


def read_banned(path: Path) -> list[str]:
    """Read the banned list (the firmware's ``kernel/banned.list``) with ``read_option_list``."""
    return read_option_list(path)


def read_exclude(path: Path) -> list[str]:
    """Read the exclude list (the firmware's ``kernel/exclude.list``) with ``read_option_list``."""
    return read_option_list(path)


def requested_by(fragment: dict[str, str]) -> set[str]:
    """The options a fragment asks to have on, from ``read_config`` output; ``n`` asks for off."""
    return {symbol for symbol, value in fragment.items() if value != "n"}


@dataclass
class Surface:
    """What a resolved config brings, which banned and excluded options it turns on, and what nobody asked for."""

    enabled: dict[str, str] = field(default_factory=dict)  # every option set to y or m, to its value
    code: dict[str, list[str]] = field(default_factory=dict)  # enabled option -> modules it builds
    unmapped: list[str] = field(default_factory=list)  # enabled options with no module mapping
    banned: dict[str, str] = field(default_factory=dict)  # banned options that are enabled, to their value
    excluded: dict[str, str] = field(default_factory=dict)  # excluded options that are enabled, to their value
    unrequested: list[str] = field(default_factory=list)  # enabled but not named by the fragment (empty if none given)


def surface(
    config: dict[str, str],
    modules: dict[str, set[str]],
    banned: Iterable[str],
    excluded: Iterable[str] = (),
    requested: set[str] | None = None,
) -> Surface:
    """Report what a resolved config enables, the banned and excluded options among it, and the unrequested ones.

    ``config`` is ``{symbol: value}`` from a resolved ``.config``; a value of ``n`` is off, and an
    option absent from it is off. Only ``y`` and ``m`` count as enabled features; any other set
    value is still checked against the banned and excluded lists. ``modules`` is ``{module: {symbols}}`` as
    ``kconfigpy.kbuild.module_map`` returns it. ``banned`` and ``excluded`` are lists from
    ``read_banned`` and ``read_exclude``. ``requested`` is ``requested_by(fragment)``; when it is
    given, ``unrequested`` lists every enabled option the fragment did not name, so that options
    switched on by ``default y`` or ``imply`` are visible.
    """
    # A set value is on for the banned and excluded checks. Only y and m are features that bring code:
    # a numeric or string option such as CONFIG_GCC_VERSION=160201 is set but is not attack surface.
    set_values = {symbol: value for symbol, value in config.items() if value != "n"}
    enabled = {symbol: value for symbol, value in set_values.items() if value in {"y", "m"}}
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
    report.banned = {symbol: set_values[symbol] for symbol in dict.fromkeys(banned) if symbol in set_values}
    report.excluded = {symbol: set_values[symbol] for symbol in dict.fromkeys(excluded) if symbol in set_values}
    if requested is not None:
        report.unrequested = [symbol for symbol in report.enabled if symbol not in requested]
    return report


def report_text(result: Surface) -> str:
    """Render the surface as Markdown: banned and excluded options first, then the code each option brings."""
    lines = ["# Attack-surface report", "", "## Banned options enabled"]
    lines += [f"- `{symbol}={value}`" for symbol, value in result.banned.items()] or ["- none"]
    lines += ["", "## Excluded options enabled"]
    lines += [f"- `{symbol}={value}`" for symbol, value in result.excluded.items()] or ["- none"]
    lines += ["", "## Code brought by enabled options"]
    lines += [f"- `{symbol}`: {', '.join(modules)}" for symbol, modules in result.code.items()] or ["- none"]
    lines += ["", "## Enabled options with no module mapping (unknown, not guessed)"]
    lines += [f"- `{symbol}`" for symbol in result.unmapped] or ["- none"]
    lines += ["", "## Enabled but not named by the fragment"]
    lines += [f"- `{symbol}`" for symbol in result.unrequested] or ["- none"]
    return "\n".join(lines) + "\n"
