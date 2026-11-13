"""The golden fragment is checked in, and CI regenerates it from the same inputs.

The golden file is built from the synthetic fixture tree, its snapshot and its exclude list. A change in the
tool that changes what gets enabled therefore fails here with a diff, not silently. Regenerate it with the
command in the failure message once the change is intended.
"""

from __future__ import annotations

import argparse
import difflib
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
TREE = FIXTURES / "kernel-tree"
SNAPSHOT = FIXTURES / "snapshot.tsv"
EXCLUDE = FIXTURES / "exclude.txt"
GOLDEN = ROOT / "tests" / "golden" / "fixture-hardware.config"


def _load_tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("update_golden", ROOT / "tools" / "update_golden.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


UPDATE = _load_tool()


def _fixture_args() -> argparse.Namespace:
    return UPDATE.parse_args(
        ["--snapshot", str(SNAPSHOT), "--tree", str(TREE), "--exclude", str(EXCLUDE), "--out", "unused"]
    )


def golden_diff(expected: str, actual: str, name: str) -> str:
    """Return a unified diff from the checked-in text to the regenerated text, or '' when they match."""
    return "".join(
        difflib.unified_diff(
            expected.splitlines(keepends=True),
            actual.splitlines(keepends=True),
            fromfile=f"{name} (checked in)",
            tofile=f"{name} (regenerated)",
        )
    )


def test_regenerated_fragment_matches_the_checked_in_golden(tmp_path: Path) -> None:
    regenerated = UPDATE.regenerate(_fixture_args(), tmp_path)
    checked_in = GOLDEN.read_text(encoding="utf-8")
    diff = golden_diff(checked_in, regenerated, GOLDEN.name)
    if diff:
        pytest.fail(
            "the regenerated fragment differs from tests/golden/ (a change in the tool changed what gets enabled).\n"
            "If that change is intended, regenerate with:\n"
            "  python tools/update_golden.py --snapshot tests/fixtures/snapshot.tsv --tree tests/fixtures/kernel-tree "
            "--exclude tests/fixtures/exclude.txt --out tests/golden/fixture-hardware.config\n\n" + diff
        )


def test_every_option_in_the_golden_has_a_reason() -> None:
    lines = GOLDEN.read_text(encoding="utf-8").splitlines()
    options = [i for i, line in enumerate(lines) if line.startswith("CONFIG_")]
    assert options, "golden fragment enables nothing"
    for index in options:
        assert lines[index - 1].startswith("# "), f"{lines[index]} has no reason above it"


def test_excluded_symbol_is_kept_out_of_the_golden() -> None:
    text = GOLDEN.read_text(encoding="utf-8")
    assert "CONFIG_ACME_SERIAL=y" not in text
    assert "CONFIG_ACME_NET=y" in text


def test_a_changed_option_shows_as_a_readable_diff(tmp_path: Path) -> None:
    golden = GOLDEN.read_text(encoding="utf-8")
    changed = golden.replace("CONFIG_PCI=y", "CONFIG_PCI=n")
    assert changed != golden
    diff = golden_diff(changed, golden, GOLDEN.name)
    assert "-CONFIG_PCI=n" in diff and "+CONFIG_PCI=y" in diff
    assert diff.startswith("--- ") and "(checked in)" in diff


def test_identical_text_gives_no_diff() -> None:
    golden = GOLDEN.read_text(encoding="utf-8")
    assert golden_diff(golden, golden, GOLDEN.name) == ""
