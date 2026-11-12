"""Which kernel CVEs apply to one version, and is the affected code even compiled in?

Input is the kernel CNA's data (git.kernel.org/pub/scm/linux/security/vulns.git). The answer is
deliberately conservative: a CVE counts as "not built" only when every file it names can be shown
to be excluded by the config. Anything unclear stays counted.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterator
from pathlib import Path, PurePosixPath

from kconfigpy.kbuild import _OBJ, _makefile_lines, _walk, object_map
from kconfigpy.verify import read_config

Version = tuple[int, ...]


def parse_version(text: str) -> Version:
    # A release candidate such as 4.4-rc1 is treated as the release it leads to.
    return tuple(int(part) for part in text.split("-", 1)[0].split("."))


def dyad_pairs(path: Path) -> list[tuple[Version, Version]]:
    pairs = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or line.count(":") != 3:
            continue
        start, _, fix, _ = line.split(":")
        pairs.append((parse_version(start), parse_version(fix)))
    return pairs


def affects(pairs: list[tuple[Version, Version]], version: Version) -> bool:
    """True if the bug is present in ``version``, using the fix on its own stable branch if any."""
    branch = version[:2]
    fixes = [fix for _, fix in pairs if fix[:2] == branch and fix <= version]
    if fixes:
        # A bug can return after its fix: an unfixed start on this branch at or after the last
        # fix reopens it (6.18.32 -> 6.18.33, then 6.18.57 -> 0).
        last_fix = max(fixes)
        return any(fix == (0,) and start[:2] == branch and last_fix <= start <= version for start, fix in pairs)
    candidate = False
    for start, fix in pairs:
        if start > version:
            continue
        if fix == (0,):
            # A zero fix means unfixed on the start's own branch, which may be long dead
            # (5.14.15 -> 0). It only says something here for this branch or a mainline start.
            candidate = candidate or start[:2] == branch or len(start) == 2
        elif fix > version:
            candidate = True
    return candidate


def directory_gates(tree: Path, arch: str) -> dict[str, set[str]]:
    """``{directory: {CONFIG}}`` from ``obj-$(CONFIG_X) += dir/`` lines."""
    gates: dict[str, set[str]] = {}
    for relative, files in _walk(tree, arch):
        for line in _makefile_lines(tree, relative, files):
            match = _OBJ.match(line)
            if match is None:
                continue
            for token in match.group(2).split("#", 1)[0].split():
                if token.endswith("/"):
                    gates.setdefault((relative / token[:-1]).as_posix(), set()).add(match.group(1))
    return gates


def _parents(path: PurePosixPath) -> Iterator[str]:
    for parent in path.parents:
        if str(parent) != ".":
            yield str(parent)


class Reach:
    def __init__(self, tree: Path, arch: str, config: dict[str, str]) -> None:
        self.arch = arch
        self.config = config
        self.objects = object_map(tree, arch)
        self.gates = directory_gates(tree, arch)

    def excluded(self, file: str) -> bool:
        path = PurePosixPath(file)
        top = path.parts[0] if path.parts else ""
        if top in {"tools", "samples", "Documentation"}:
            return True
        if top == "arch" and len(path.parts) > 1 and path.parts[1] != self.arch:
            return True
        for directory in _parents(path):
            if directory in self.gates and not self.gates[directory] & set(self.config):
                return True
        if path.suffix == ".c":
            symbols = self.objects.get(str(path.with_suffix("")))
            if not symbols:
                return False
            return not symbols & set(self.config)
        return False


def program_files(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    files: set[str] = set()
    for item in data.get("containers", {}).get("cna", {}).get("affected", []):
        files.update(item.get("programFiles", []))
    return sorted(files)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tree", type=Path, required=True)
    parser.add_argument("--vulns", type=Path, required=True, help="checkout of the kernel CNA vulns repo")
    parser.add_argument("--version", required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--arch", default="x86")
    parser.add_argument("--out", type=Path, help="write the CVE list as JSON")
    args = parser.parse_args()

    version = parse_version(args.version)
    reach = Reach(args.tree, args.arch, read_config(args.config))
    built: list[str] = []
    excluded: list[str] = []
    for dyad in sorted((args.vulns / "cve" / "published").glob("*/*.dyad")):
        if not affects(dyad_pairs(dyad), version):
            continue
        files = program_files(dyad.with_suffix(".json"))
        (excluded if files and all(reach.excluded(f) for f in files) else built).append(dyad.stem)
    print(
        f"{args.version}: affects {len(built) + len(excluded)}, compiled in or unclear {len(built)}, not built {len(excluded)}"
    )
    if args.out:
        args.out.write_text(
            json.dumps({"version": args.version, "built_or_unclear": built, "not_built": excluded}), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
