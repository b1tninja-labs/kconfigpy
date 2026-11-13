"""Options the kernel's reproducible-builds document names as breaking a reproducible build."""

from __future__ import annotations

from pathlib import Path

import pytest

from kconfigpy.reproducible import NAMED_OPTIONS, flag_reproducibility
from kconfigpy.verify import read_config

SECTIONS = {
    "IKHEADERS": "Timestamps",
    "DEBUG_EFI": "Absolute filenames",
    "MODULE_SIG_ALL": "Module signing",
    "RANDSTRUCT": "Structure randomisation",
}


@pytest.mark.parametrize(("symbol", "section"), sorted(SECTIONS.items()))
def test_named_option_is_flagged_with_its_section(symbol: str, section: str) -> None:
    flags = flag_reproducibility({symbol: "y"})
    assert [(f.symbol, f.section) for f in flags] == [(symbol, section)]
    assert flags[0].reason


def test_every_documented_option_stays_flagged() -> None:
    assert set(NAMED_OPTIONS) == set(SECTIONS)
    flagged = {f.symbol for f in flag_reproducibility(dict.fromkeys(SECTIONS, "y"))}
    assert flagged == set(SECTIONS)


def test_off_and_absent_options_are_not_flagged() -> None:
    assert flag_reproducibility({"DEBUG_EFI": "n", "IKHEADERS": ""}) == []
    assert flag_reproducibility({}) == []


def test_module_value_counts_and_prefix_is_accepted() -> None:
    flags = flag_reproducibility({"CONFIG_IKHEADERS": "m"})
    assert [(f.symbol, f.value) for f in flags] == [("IKHEADERS", "m")]


def test_build_salt_is_not_flagged() -> None:
    # The document presents CONFIG_BUILD_SALT as the remedy for output being too reproducible.
    assert flag_reproducibility({"BUILD_SALT": '"x"'}) == []


def test_reads_a_config_file(tmp_path: Path) -> None:
    path = tmp_path / "frag"
    path.write_text('CONFIG_DEBUG_EFI=y\nCONFIG_BUILD_SALT="s"\n# CONFIG_RANDSTRUCT is not set\n', encoding="utf-8")
    assert [f.symbol for f in flag_reproducibility(read_config(path))] == ["DEBUG_EFI"]
