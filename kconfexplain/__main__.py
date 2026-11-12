"""Command line: ``python -m kconfexplain trace|verify``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from kconfexplain.kbuild import driver_sources, module_map, normalize
from kconfexplain.kconfig import read_kconfig
from kconfexplain.trace import fragment_text, read_aliases, read_snapshot, report_text, trace
from kconfexplain.verify import read_config, verify


def _trace(args: argparse.Namespace) -> int:
    db = read_kconfig(args.tree, args.arch)
    modules = module_map(args.tree, args.arch)
    aliases = read_aliases(args.aliases) if args.aliases else []
    snapshot = read_snapshot(args.snapshot)
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
    trace_cmd = commands.add_parser("trace", help="hardware snapshot to config fragment")
    trace_cmd.add_argument("--tree", type=Path, required=True)
    trace_cmd.add_argument("--snapshot", type=Path, required=True)
    trace_cmd.add_argument("--aliases", type=Path, help="modules.alias, to find drivers for unbound devices")
    trace_cmd.add_argument("--arch", default="x86")
    trace_cmd.add_argument("--out", type=Path, required=True)
    trace_cmd.set_defaults(run=_trace)
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
