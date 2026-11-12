"""Command line: ``python -m kconfexplain snapshot|generate|verify``.

``snapshot`` exports the hardware snapshot of this machine, or of a remote one over SSH.
``generate`` writes the config fragment from a saved snapshot, or from a fresh one with ``--current``.
``verify`` checks a fragment against the kernel's own resolved ``.config``.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from kconfexplain import snapshot as snapshot_module
from kconfexplain.kbuild import driver_sources, module_map, normalize
from kconfexplain.kconfig import read_kconfig
from kconfexplain.trace import fragment_text, read_aliases, read_snapshot, report_text, trace
from kconfexplain.verify import read_config, verify


def collect(ssh: str | None = None, ssh_cmd: str = "ssh") -> str:
    """Snapshot text from this machine, or from ``ssh`` target by piping the snapshot module to its python3."""
    if not ssh:
        return "\n".join(snapshot_module.records()) + "\n"
    source = Path(snapshot_module.__file__).read_bytes()
    proc = subprocess.run(
        [*ssh_cmd.split(), ssh, "python3 -"], input=source, capture_output=True, check=False
    )
    if proc.returncode != 0:
        raise RuntimeError(f"snapshot over ssh failed (exit {proc.returncode}): {proc.stderr.decode(errors='replace').strip()}")
    text = proc.stdout.decode("utf-8", errors="replace")
    if not any(line.startswith("dev	") for line in text.splitlines()):
        raise RuntimeError(f"snapshot from {ssh} has no device records: refusing to use it")
    return text


def _snapshot(args: argparse.Namespace) -> int:
    text = collect(args.ssh, args.ssh_cmd)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(f"snapshot: {len(text.splitlines())} records written to {args.out}")
    else:
        sys.stdout.write(text)
    return 0


def _generate(args: argparse.Namespace) -> int:
    if args.current:
        args.out.mkdir(parents=True, exist_ok=True)
        args.snapshot = args.out / "snapshot.tsv"
        args.snapshot.write_text(collect(args.ssh, args.ssh_cmd), encoding="utf-8")
    db = read_kconfig(args.tree, args.arch)
    modules = module_map(args.tree, args.arch)
    aliases = read_aliases(args.aliases) if args.aliases else []
    snapshot = read_snapshot(args.snapshot)
    if not snapshot.devices:
        raise RuntimeError(f"{args.snapshot} has no device records: a fragment from it would be empty, so it is refused")
    names = {d.driver for d in snapshot.devices if d.driver and not d.module and normalize(d.driver) not in modules}
    ambiguous: dict[str, list[str]] = {}
    for name, symbols in driver_sources(args.tree, names, args.arch).items():
        if len(symbols) == 1:
            modules[normalize(name)] = symbols
        elif symbols:
            ambiguous[normalize(name)] = sorted(symbols)
    result = trace(snapshot, db, modules, aliases)
    result.ambiguous = ambiguous
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "hardware.config").write_text(fragment_text(result), encoding="utf-8")
    (args.out / "report.md").write_text(report_text(result), encoding="utf-8")
    bound = sum(row.status == "bound" for row in result.rows)
    print(
        f"symbols read: {len(db.definitions)}, modules mapped: {len(modules)}, missing sources: {len(db.missing_sources)}"
    )
    print(
        f"devices: {len(result.rows)} ({bound} bound), options enabled: {len(result.solution.enabled)}, conflicts: {len(result.solution.conflicts)}"
    )
    return 0


def _verify(args: argparse.Namespace) -> int:
    db = read_kconfig(args.tree, args.arch)
    result = verify(read_config(args.fragment), read_config(args.config), db)
    print(f"kept: {len(result.kept)}, dropped: {len(result.dropped)}")
    for symbol, failing in result.dropped.items():
        print(f"  dropped {symbol}: {', '.join(failing) or 'no failing dependency found'}")
    return 1 if result.dropped else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kconfexplain", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    snap = commands.add_parser("snapshot", help="export the hardware snapshot of this machine or an SSH host")
    snap.add_argument("--ssh", metavar="HOST", help="read this SSH host instead of the local machine")
    snap.add_argument("--ssh-cmd", default="ssh", help="ssh client command, for example 'plink -batch -agent'")
    snap.add_argument("--out", type=Path, help="write here instead of stdout")
    snap.set_defaults(run=_snapshot)

    gen = commands.add_parser("generate", help="config fragment from a snapshot, saved or current")
    source = gen.add_mutually_exclusive_group(required=True)
    source.add_argument("--snapshot", type=Path, help="a snapshot file from the snapshot command")
    source.add_argument("--current", action="store_true", help="collect a fresh snapshot first")
    gen.add_argument("--ssh", metavar="HOST", help="with --current: collect from this SSH host")
    gen.add_argument("--ssh-cmd", default="ssh", help="ssh client command")
    gen.add_argument("--tree", type=Path, required=True)
    gen.add_argument("--aliases", type=Path, help="modules.alias, to find drivers for unbound devices")
    gen.add_argument("--arch", default="x86")
    gen.add_argument("--out", type=Path, required=True)
    gen.set_defaults(run=_generate)

    trace_cmd = commands.add_parser("trace", help="alias of generate --snapshot")
    trace_cmd.add_argument("--tree", type=Path, required=True)
    trace_cmd.add_argument("--snapshot", type=Path, required=True)
    trace_cmd.add_argument("--aliases", type=Path, help="modules.alias, to find drivers for unbound devices")
    trace_cmd.add_argument("--arch", default="x86")
    trace_cmd.add_argument("--out", type=Path, required=True)
    trace_cmd.set_defaults(run=_generate, current=False, ssh=None, ssh_cmd="ssh")

    verify_cmd = commands.add_parser("verify", help="compare a fragment with a resolved .config")
    verify_cmd.add_argument("--tree", type=Path, required=True)
    verify_cmd.add_argument("--fragment", type=Path, required=True)
    verify_cmd.add_argument("--config", type=Path, required=True)
    verify_cmd.add_argument("--arch", default="x86")
    verify_cmd.set_defaults(run=_verify)

    args = parser.parse_args(argv)
    return int(args.run(args))


if __name__ == "__main__":
    sys.exit(main())
