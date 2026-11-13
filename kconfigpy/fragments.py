"""Fragments made from configurations: a diff of two ``.config`` files, and a minimal defconfig.

Both functions are pure. They take the ``{symbol: value}`` mapping that ``kconfigpy.verify.read_config``
returns, in which an option that is off or unset is simply absent, and they return :class:`FragmentLine`
records. ``render`` turns the records into fragment text; each line is preceded by a ``# reason`` comment, so
the provenance travels with the file and ``conf`` still reads it (a comment that is not
``# CONFIG_X is not set`` is ignored).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class FragmentLine:
    """One option of a fragment: ``value`` is ``None`` for ``# CONFIG_X is not set``."""

    symbol: str
    value: str | None
    reason: str

    @property
    def text(self) -> str:
        if self.value is None:
            return f"# CONFIG_{self.symbol} is not set"
        return f"CONFIG_{self.symbol}={self.value}"


def render(lines: Iterable[FragmentLine]) -> str:
    """Fragment text, one ``# reason`` comment above each option line."""
    out: list[str] = []
    for line in lines:
        out.append(f"# {line.reason}")
        out.append(line.text)
    return "".join(f"{text}\n" for text in out)


def diff_fragment(golden: dict[str, str], build: dict[str, str]) -> list[FragmentLine]:
    """The fragment that turns ``golden`` into ``build``, one line per option that differs.

    - in both with different values: ``CONFIG_X=<build value>``, reason ``changed from <old> to <new>``;
    - only in ``golden`` (off or unset in the build): ``# CONFIG_X is not set``, reason ``only in golden``;
    - only in ``build``: ``CONFIG_X=<build value>``, reason ``only in build``.

    Options with the same value in both are left out. Lines are sorted by symbol.
    """
    lines: list[FragmentLine] = []
    for symbol in sorted(golden.keys() | build.keys()):
        old, new = golden.get(symbol), build.get(symbol)
        if old == new:
            continue
        if old is None:
            lines.append(FragmentLine(symbol, new, "only in build"))
        elif new is None:
            lines.append(FragmentLine(symbol, None, "only in golden"))
        else:
            lines.append(FragmentLine(symbol, new, f"changed from {old} to {new}"))
    return lines


def minimal_defconfig(full: dict[str, str], baseline: dict[str, str]) -> list[FragmentLine]:
    """Keep only the options of ``full`` that differ from ``baseline``.

    ``full`` is a complete resolved ``.config``. ``baseline`` is what the kernel resolves on its own with no
    fragment at all, that is the ``.config`` that ``conf`` writes for an empty input (``make alldefconfig``).
    Producing it needs the kernel's ``conf``, so the caller supplies it; this function never evaluates a
    ``default``, ``select`` or ``depends on`` itself.

    "Minimal" therefore means: no line repeats the baseline, and ``baseline`` plus the lines reproduces
    ``full`` exactly, one option at a time. An option set in ``full`` with another value or absent from
    ``baseline`` is written as ``CONFIG_X=v``; an option set in ``baseline`` and off in ``full`` is written
    as ``# CONFIG_X is not set``.

    What it does not know: an option that ``conf`` would turn on anyway because a *kept* option selects it
    or its default depends on a kept option is still written, since that needs the Kconfig graph and a
    fixed point. The result is a correct defconfig that can be longer than ``make savedefconfig`` writes,
    never one that resolves differently. Run ``conf`` over the result and compare with ``full`` to prove it.
    """
    lines: list[FragmentLine] = []
    for symbol in sorted(full.keys() | baseline.keys()):
        want, base = full.get(symbol), baseline.get(symbol)
        if want == base:
            continue
        if want is None:
            lines.append(FragmentLine(symbol, None, f"off here, the kernel's own default is {base}"))
        elif base is None:
            lines.append(FragmentLine(symbol, want, "set here, off by the kernel's own default"))
        else:
            lines.append(FragmentLine(symbol, want, f"differs from the kernel's own default {base}"))
    return lines
