"""Regenerate the golden fragment from a snapshot, a kernel tree and an exclude list.

The golden file is checked in. CI regenerates it from the same inputs and compares; a change in the tool
then shows up as a diff rather than as a silent change in what gets enabled.

Usage::

    python tools/update_golden.py --snapshot SNAP --tree TREE --out tests/golden/hardware.config
    python tools/update_golden.py ... --exclude EXCLUDE --aliases MODULES_ALIAS --arch x86

The script only writes the fragment and nothing else. It refuses an empty snapshot, the same as ``generate``.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from kconfigpy.__main__ import main as kconfigpy_main


def build_argv(args: argparse.Namespace, scratch: Path) -> list[str]:
    """The ``generate`` arguments that write the fragment into a scratch directory."""
    argv = ["generate", "--snapshot", str(args.snapshot), "--tree", str(args.tree), "--out", str(scratch)]
    if args.aliases:
        argv += ["--aliases", str(args.aliases)]
    if args.exclude:
        argv += ["--exclude", str(args.exclude)]
    argv += ["--arch", args.arch]
    return argv


def regenerate(args: argparse.Namespace, scratch: Path) -> str:
    """Run ``generate`` into ``scratch`` and return the fragment text it wrote."""
    code = kconfigpy_main(build_argv(args, scratch))
    if code != 0:
        raise RuntimeError(f"generate failed with exit {code}")
    return (scratch / "hardware.config").read_text(encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--snapshot", type=Path, required=True, help="a snapshot file from the snapshot command")
    parser.add_argument("--tree", type=Path, required=True, help="the kernel source tree")
    parser.add_argument("--aliases", type=Path, help="modules.alias, to find drivers for unbound devices")
    parser.add_argument("--exclude", type=Path, help="symbols never to enable, one per line")
    parser.add_argument("--arch", default="x86")
    parser.add_argument("--out", type=Path, required=True, help="where to write the golden fragment")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    with tempfile.TemporaryDirectory() as scratch:
        text = regenerate(args, Path(scratch))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8", newline="\n")
    print(f"golden: {len(text.splitlines())} lines written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
