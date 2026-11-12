"""Map kernel modules, objects and driver names to the config symbols that build them."""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

_SKIP_TOP = {"Documentation", "LICENSES", "samples", "scripts", "tools", "usr"}
ALIAS_FILES = ("modules.alias", "modules.builtin.alias")
_MODULES_ON = re.compile(r"^CONFIG_MODULES=y\s*$", re.MULTILINE)
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


class BuildArtifactsMissing(FileNotFoundError):
    """The built tree lacks the ``depmod`` output that aliases come from."""


def module_aliases(tree: Path) -> list[tuple[str, str]]:
    """Read ``modules.alias`` and ``modules.builtin.alias`` from a built tree as ``(pattern, module)`` pairs.

    Both files are written by ``depmod`` from the ``modpost`` output of a finished build. They are read,
    never derived: a ``MODULE_DEVICE_TABLE`` in a source file says what the source could build, not what
    this build contains. When either file is missing this refuses, because an empty table would make every
    device look unclaimed rather than unknown.
    """
    missing = [name for name in ALIAS_FILES if not (tree / name).is_file()]
    if missing:
        raise BuildArtifactsMissing(
            f"{tree} has no {' or '.join(missing)}: these are depmod output from a finished build, "
            "not derivable from the sources; run depmod on the built modules first"
        )
    pairs: list[tuple[str, str]] = []
    for name in ALIAS_FILES:
        for line in (tree / name).read_text(encoding="utf-8", errors="replace").splitlines():
            parts = line.split()
            if len(parts) == 3 and parts[0] == "alias":
                pairs.append((parts[1], normalize(parts[2])))
    return pairs


@dataclass(frozen=True)
class BuiltinMap:
    """Driver names mapped to the symbols that build them into the kernel, and the line the report states."""

    modules_enabled: bool
    drivers: dict[str, set[str]]
    statement: str


def modules_enabled(config: Path) -> bool:
    """True only when the ``.config`` says ``CONFIG_MODULES=y``; an absent or ``not set`` line means off."""
    return _MODULES_ON.search(config.read_text(encoding="utf-8", errors="replace")) is not None


def builtin_map(config: Path, tree: Path, names: set[str], arch: str = "x86") -> BuiltinMap:
    """With ``CONFIG_MODULES`` off, map each driver name to the symbols that must be ``=y``.

    No module can be loaded in that kernel, so every driver is built in. The statement says so and
    lists the drivers that could not be mapped, for the report to carry.
    """
    if modules_enabled(config):
        return BuiltinMap(
            True, {}, f"CONFIG_MODULES is on in {config.name}: drivers load as modules, none is built in."
        )
    wanted = {normalize(name) for name in names}
    modules = module_map(tree, arch)
    found = {name: modules[name] for name in wanted if name in modules}
    for name, symbols in driver_sources(tree, wanted - set(found), arch).items():
        found.setdefault(name, set()).update(symbols)
    unmapped = sorted(wanted - set(found))
    statement = (
        f"CONFIG_MODULES is off in {config.name}: no module can be loaded, so {len(found)} driver(s) "
        f"are mapped to built-in symbols that must be =y ({', '.join(sorted(found)) or 'none'}); "
        f"{len(unmapped)} driver(s) have no built-in symbol ({', '.join(unmapped) or 'none'})."
    )
    return BuiltinMap(False, found, statement)
