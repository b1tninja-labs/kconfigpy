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

from kconfigpy.kconfig import KconfigDb


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


def minimal_defconfig(
    full: dict[str, str], baseline: dict[str, str], db: KconfigDb | None = None
) -> list[FragmentLine]:
    """Keep only the options of ``full`` that differ from ``baseline``, as ``make savedefconfig`` does.

    ``make savedefconfig`` (``conf_write_defconfig``) writes a symbol only when it passes two tests: the
    user can change it (it has a visible prompt), and its value is not the default that ``conf`` computes
    for it in the resolved configuration. kconfgen's split mode applies the same two tests. This function
    applies them with what it can know:

    - the default is taken from ``baseline``, the ``.config`` that ``conf`` writes for an empty input
      (``make alldefconfig``). The caller supplies it because producing it needs the kernel's ``conf``;
      this function never evaluates a ``default``, ``select`` or ``depends on`` itself;
    - when ``db`` is given, an option the Kconfig tree defines without any prompt is dropped, because
      ``conf`` derives it and the user cannot set it. An option ``db`` does not define is kept, never
      guessed away.

    An option set in ``full`` with another value or absent from ``baseline`` is written as ``CONFIG_X=v``;
    one set in ``baseline`` and off in ``full`` as ``# CONFIG_X is not set``. Lines are sorted by symbol.

    What it does not know: ``savedefconfig`` compares with the default *in the context of the full
    config*, so an option that is on only because a kept option selects it, or whose default depends on a
    kept option, is dropped by ``savedefconfig`` but kept here when ``baseline`` lacks it and it has a
    prompt. The reverse also happens: an option that ``full`` leaves off but whose default turns on once a
    kept option satisfies its dependencies is absent from both ``full`` and ``baseline``, so nothing here
    says to turn it off. ``close_fragment`` repairs that from one run of ``conf``. An option that is an int,
    hex or string and set in ``baseline`` but absent from ``full`` cannot be written as "not set" and is
    left out; it is absent because a dependency is off.

    It is the kernel's ``conf`` that proves a result: expand it, and ``close_fragment`` until it matches.
    """
    lines: list[FragmentLine] = []
    for symbol in sorted(full.keys() | baseline.keys()):
        want, base = full.get(symbol), baseline.get(symbol)
        if want == base:
            continue
        if db is not None and symbol in db.definitions and not db.has_prompt(symbol):
            continue
        if want is None:
            if base not in ("y", "m"):
                continue  # an int, hex or string has no "not set" form; it is absent because a dependency is off
            lines.append(FragmentLine(symbol, None, f"off here, the kernel's own default is {base}"))
        elif base is None:
            lines.append(FragmentLine(symbol, want, "set here, off by the kernel's own default"))
        else:
            lines.append(FragmentLine(symbol, want, f"differs from the kernel's own default {base}"))
    return lines


def close_fragment(full: dict[str, str], lines: list[FragmentLine], expanded: dict[str, str]) -> list[FragmentLine]:
    """Add the lines that make ``conf``'s expansion of ``lines`` match ``full``, given that expansion.

    ``expanded`` is the ``.config`` that ``conf`` wrote for ``lines`` as input. An option on in ``expanded``
    (``y`` or ``m``) and absent from ``full`` is added as ``# CONFIG_X is not set``; an option in ``full``
    with another value, or absent, in ``expanded`` is added as ``CONFIG_X=v``. Run ``conf`` again on the
    result and repeat until nothing is added; an empty return of added lines means the fragment is exact.
    An option that is neither (an int or string that ``expanded`` has and ``full`` lacks) cannot be turned
    off and is left alone.
    """
    have = {line.symbol for line in lines}
    added: list[FragmentLine] = []
    for symbol in sorted(full.keys() | expanded.keys()):
        want, got = full.get(symbol), expanded.get(symbol)
        if want == got or symbol in have:
            continue
        if want is None:
            if got in ("y", "m"):
                added.append(FragmentLine(symbol, None, "conf turns it on by default; off in the full config"))
        else:
            added.append(FragmentLine(symbol, want, "conf does not reach this value from the fragment"))
    return sorted([*lines, *added], key=lambda line: line.symbol)
