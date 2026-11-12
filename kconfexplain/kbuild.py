"""Map kernel modules, objects and driver names to the config symbols that build them."""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from pathlib import Path

_SKIP_TOP = {"Documentation", "LICENSES", "samples", "scripts", "tools", "usr"}
_OBJ = re.compile(r"^\s*obj-\$\(CONFIG_([A-Za-z0-9_]+)\)\s*(?:\+=|:=|=)\s*(.*)$")
_COMPOSITE = re.compile(r"^\s*([A-Za-z0-9_\-]+)-(?:objs|y)\s*(?:\+=|:=|=)\s*(.*)$")


def normalize(module: str) -> str:
    """Module names treat ``-`` and ``_`` as the same character."""
    return module.replace("-", "_")


def _logical_lines(text: str) -> list[str]:
    joined = re.sub(r"\\\r?\n", " ", text)
    return joined.splitlines()


def _walk(tree: Path, arch: str) -> Iterator[tuple[Path, list[str]]]:
    for root, dirs, files in os.walk(tree):
        relative = Path(root).relative_to(tree)
        if relative == Path("."):
            dirs[:] = [d for d in dirs if d not in _SKIP_TOP and not d.startswith(".")]
        elif relative == Path("arch"):
            dirs[:] = [d for d in dirs if d == arch]
        yield relative, files


def _objects(value: str) -> list[str]:
    return [token[:-2] for token in value.split("#", 1)[0].split() if token.endswith(".o")]


def _makefile_lines(tree: Path, relative: Path, files: list[str]) -> list[str]:
    lines: list[str] = []
    for name in files:
        if name in {"Makefile", "Kbuild"}:
            lines += _logical_lines((tree / relative / name).read_text(encoding="utf-8", errors="replace"))
    return lines


def module_map(tree: Path, arch: str = "x86") -> dict[str, set[str]]:
    """Return ``{module: {CONFIG symbols}}`` for every ``obj-$(CONFIG_X) += name.o``."""
    result: dict[str, set[str]] = {}
    for relative, files in _walk(tree, arch):
        for line in _makefile_lines(tree, relative, files):
            match = _OBJ.match(line)
            if match is not None:
                for token in _objects(match.group(2)):
                    result.setdefault(normalize(token.rsplit("/", 1)[-1]), set()).add(match.group(1))
    return result


def object_map(tree: Path, arch: str = "x86") -> dict[str, set[str]]:
    """Return ``{source path without extension: {CONFIG symbols}}``, following composite objects."""
    result: dict[str, set[str]] = {}
    for relative, files in _walk(tree, arch):
        lines = _makefile_lines(tree, relative, files)
        composites: dict[str, list[str]] = {}
        for line in lines:
            match = _COMPOSITE.match(line)
            if match is not None and match.group(1) != "obj":
                composites.setdefault(match.group(1), []).extend(_objects(match.group(2)))
        for line in lines:
            match = _OBJ.match(line)
            if match is None:
                continue
            for token in _objects(match.group(2)):
                for stem in [token, *composites.get(token, [])]:
                    result.setdefault((relative / stem).as_posix(), set()).add(match.group(1))
    return result


def driver_sources(tree: Path, names: set[str], arch: str = "x86") -> dict[str, set[str]]:
    """Find C files registering ``.name = "driver"`` and return the symbols that build them.

    A registered driver name often differs from its module: ``sd`` is built as ``sd_mod``.
    """
    if not names:
        return {}
    objects = object_map(tree, arch)
    pattern = re.compile(r'\.name\s*=\s*"(' + "|".join(re.escape(name) for name in sorted(names)) + r')"')
    result: dict[str, set[str]] = {}
    for relative, files in _walk(tree, arch):
        for name in files:
            if not name.endswith(".c"):
                continue
            text = (tree / relative / name).read_text(encoding="utf-8", errors="replace")
            for found in set(pattern.findall(text)):
                symbols = objects.get((relative / name[:-2]).as_posix(), set())
                result.setdefault(found, set()).update(symbols)
    return result
