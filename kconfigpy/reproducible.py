"""Options that break reproducible builds, as Documentation/kbuild/reproducible-builds.rst names them.

Every entry below is taken from that document in the pinned 6.18.62 tree and carries the heading of the
section that names it. The list is deliberately short: an option the document does not name as breaking
reproducibility is not flagged. ``CONFIG_BUILD_SALT`` in particular is not here, because the document
introduces it as the cure for output being *too* reproducible (the "Debug info conflicts" section).
"""

from __future__ import annotations

from dataclasses import dataclass

DOCUMENT = "Documentation/kbuild/reproducible-builds.rst"


@dataclass(frozen=True)
class Flag:
    """One enabled option that the kernel documentation says makes a build unreproducible."""

    symbol: str
    value: str
    reason: str
    section: str


# symbol -> (reason, section heading in DOCUMENT)
_NAMED: dict[str, tuple[str, str]] = {
    "IKHEADERS": (
        "embeds the kernel headers with their file modification times, so the output differs between builds",
        "Timestamps",
    ),
    "DEBUG_EFI": (
        "embeds absolute paths in object files; the document says such options should be disabled",
        "Absolute filenames",
    ),
    "MODULE_SIG_ALL": (
        "by default generates a different temporary signing key for each build, so the modules differ",
        "Module signing",
    ),
    "RANDSTRUCT": (
        "needs a pre-generated seed in scripts/basic/randstruct.seed so each build uses the same value",
        "Structure randomisation",
    ),
}

NAMED_OPTIONS: tuple[str, ...] = tuple(_NAMED)


def _enabled(value: str) -> bool:
    return value not in ("", "n")


def flag_reproducibility(config: dict[str, str]) -> list[Flag]:
    """Return every enabled option in ``config`` that the kernel documentation names as breaking reproducibility.

    ``config`` maps a symbol, with or without the ``CONFIG_`` prefix, to its value, as
    ``kconfigpy.verify.read_config`` returns it. An option that is absent or ``n`` is not flagged.
    """
    flags: list[Flag] = []
    for raw, value in config.items():
        symbol = raw.removeprefix("CONFIG_")
        named = _NAMED.get(symbol)
        if named is not None and _enabled(value):
            flags.append(Flag(symbol, value, named[0], named[1]))
    return sorted(flags, key=lambda flag: flag.symbol)
