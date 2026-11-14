"""Differential check: kconfigpy's proposals against the kernel's own ``conf``.

For each requested symbol this asks kconfigpy for the options it proposes, then asks the kernel's
``conf`` to resolve that same fragment (``make allnoconfig`` with ``KCONFIG_ALLCONFIG`` set to the fragment,
in the pinned builder image). It then reports which proposed options ``conf`` dropped, which options
``conf`` enabled that kconfigpy did not mention, and the agreement rate. docs/conformance.md quotes the
numbers this prints. Run it again when the kernel or the solver changes:

    python tools/conformance.py --volume rooter-build --sample 200 --seed 1 --out <scratch dir>

Only ``conf`` decides what a configuration resolves to; this script never does. Requests whose proposal
is empty are still resolved, so a default-on option that ``conf`` adds shows up as an extra.
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kconfigpy.kbuild import module_map, normalize
from kconfigpy.kconfig import KconfigDb, read_kconfig
from kconfigpy.solve import Solver
from kconfigpy.trace import read_snapshot
from kconfigpy.verify import read_config

KERNEL = "/work/src/linux-6.18.62"
DEFAULT_IMAGE = "rooter-builder:latest"
DEFAULT_VOLUME = "rooter-build"


@dataclass
class Comparison:
    """One request: what kconfigpy proposed against what ``conf`` kept as y."""

    request: str
    proposed: set[str]
    resolved: set[str]
    dropped: set[str] = field(init=False)  # proposed, but conf did not keep it
    extra: set[str] = field(init=False)  # conf enabled it, kconfigpy did not mention it

    def __post_init__(self) -> None:
        self.dropped = self.proposed - self.resolved
        self.extra = self.resolved - self.proposed


def propose(db: KconfigDb, request: str) -> set[str]:
    """The options kconfigpy proposes for one requested symbol, without its forced ones."""
    solver = Solver(db)
    solver.want(request, "requested")
    return set(solver.solution.enabled)


def fragment_text(options: Iterable[str]) -> str:
    return "".join(f"CONFIG_{name}=y\n" for name in sorted(options))


def resolved_on(config: dict[str, str]) -> set[str]:
    """Symbols conf resolved as y. ``m`` is left out: kconfigpy only proposes y."""
    return {name for name, value in config.items() if value == "y"}


def summarize(comparisons: list[Comparison]) -> dict[str, object]:
    """Aggregate over requests: kept share of proposals, share of conf's options proposed, and kinds of drop."""
    proposed = sum(len(c.proposed) for c in comparisons)
    kept = sum(len(c.proposed & c.resolved) for c in comparisons)
    resolved = sum(len(c.resolved) for c in comparisons)
    dropped_kinds: dict[str, int] = {}
    for c in comparisons:
        for name in c.dropped:
            dropped_kinds[name] = dropped_kinds.get(name, 0) + 1
    return {
        "requests": len(comparisons),
        "requests_with_no_drop": sum(not c.dropped for c in comparisons),
        "proposed": proposed,
        "kept": kept,
        "dropped": proposed - kept,
        "conf_enabled": resolved,
        "extra": sum(len(c.extra) for c in comparisons),
        "kept_share": (kept / proposed) if proposed else None,
        "proposed_share_of_conf": (kept / resolved) if resolved else None,
        "most_dropped": sorted(dropped_kinds.items(), key=lambda kv: (-kv[1], kv[0]))[:10],
    }


def extract_kconfig(volume: str, image: str, into: Path) -> Path:
    """Copy the pinned tree's Kconfig files out of the builder volume, so kconfigpy can read them."""
    listing = into / "kconfig-files.txt"
    archive = into / "kconfig.tar"
    script = (
        f"cd {KERNEL} && find . \\( -name 'Kconfig*' -o -name 'Makefile*' -o -name 'Kbuild*' \\) -type f"
        " > /io/kconfig-files.txt"
        " && tar -cf /io/kconfig.tar -T /io/kconfig-files.txt"
    )
    run(["docker", "run", "--rm", "-v", f"{volume}:/work:ro", "-v", f"{into}:/io", image, "sh", "-c", script])
    with tarfile.open(archive) as tar:
        tar.extractall(into / "tree", filter="data")
    listing.unlink(missing_ok=True)
    return into / "tree"


def resolve_batch(fragments: dict[str, str], volume: str, image: str, scratch: Path) -> dict[str, dict[str, str]]:
    """Resolve every fragment with the kernel's ``conf`` in one container run; one output directory each."""
    frag_dir = scratch / "frag"
    out_dir = scratch / "out"
    frag_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    for index, text in enumerate(fragments.values()):
        (frag_dir / f"{index}.config").write_text(text, encoding="utf-8")
    script = (
        "for f in /io/frag/*.config; do n=$(basename $f .config); mkdir -p /io/out/$n;"
        f" make -s -C {KERNEL} O=/io/out/$n ARCH=x86_64 KCONFIG_ALLCONFIG=$f allnoconfig >/io/out/$n/log 2>&1"
        " || echo FAIL $n >> /io/out/failures.txt; done"
    )
    run(["docker", "run", "--rm", "-v", f"{volume}:/work:ro", "-v", f"{scratch}:/io", image, "sh", "-c", script])
    resolved: dict[str, dict[str, str]] = {}
    for index, request in enumerate(fragments):
        config = out_dir / str(index) / ".config"
        if config.is_file():
            resolved[request] = read_config(config)
    return resolved


def run(command: list[str]) -> None:
    proc = subprocess.run(command, capture_output=True, text=True, check=False, timeout=3600)
    if proc.returncode != 0:
        raise RuntimeError(f"{command[0]} failed ({proc.returncode}): {proc.stderr.strip()[-2000:]}")


def bound_symbols(snapshot: Path, tree: Path) -> list[str]:
    """Symbols the snapshot's bound drivers map to, through the kernel's Makefiles."""
    modules = module_map(tree, "x86")
    names: set[str] = set()
    for device in read_snapshot(snapshot).devices:
        name = device.module or normalize(device.driver)
        names |= modules.get(name, set())
    return sorted(names)


def requests_from(args: argparse.Namespace, db: KconfigDb, tree: Path) -> list[str]:
    names: list[str] = []
    if args.requests:
        names += [line.strip() for line in args.requests.read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.snapshot:
        names += bound_symbols(args.snapshot, tree)
    if args.sample:
        settable = sorted(name for name in db.definitions if db.is_settable(name))
        names += random.Random(args.seed).sample(settable, min(args.sample, len(settable)))
    return list(dict.fromkeys(names))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tree", type=Path, help="a host copy of the Kconfig files; otherwise extracted from --volume")
    parser.add_argument("--volume", default=DEFAULT_VOLUME, help="docker volume holding the pinned kernel tree")
    parser.add_argument("--image", default=DEFAULT_IMAGE, help="builder image with make and conf")
    parser.add_argument("--requests", type=Path, help="one symbol per line, each resolved as its own request")
    parser.add_argument("--snapshot", type=Path, help="a hardware snapshot: every symbol its bound drivers map to")
    parser.add_argument("--sample", type=int, default=0, help="also a seeded random sample of settable symbols")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--out", type=Path, required=True, help="write results.jsonl and summary.json here")
    args = parser.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="conformance-"))
    try:
        tree = args.tree or extract_kconfig(args.volume, args.image, scratch)
        db = read_kconfig(tree, "x86")
        names = requests_from(args, db, tree)
        proposals = {name: propose(db, name) for name in names}
        fragments = {name: fragment_text(proposals[name]) for name in names}
        resolved = resolve_batch(fragments, args.volume, args.image, scratch)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    missing = [name for name in names if name not in resolved]
    if missing:
        raise RuntimeError(f"conf produced no .config for {len(missing)} requests, first: {missing[:5]}")
    comparisons = [Comparison(name, proposals[name], resolved_on(resolved[name])) for name in names]
    summary = summarize(comparisons)
    with (args.out / "results.jsonl").open("w", encoding="utf-8") as handle:
        for c in comparisons:
            row = {"request": c.request, "dropped": sorted(c.dropped), "extra_count": len(c.extra)}
            handle.write(json.dumps(row) + "\n")
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
