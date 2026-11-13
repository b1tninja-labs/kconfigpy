"""An exclude list: a symbol the caller does not want is never enabled, and nothing it selects is followed."""

from __future__ import annotations

from pathlib import Path

import pytest

from kconfigpy.__main__ import main
from kconfigpy.kconfig import read_kconfig
from kconfigpy.solve import Solver
from kconfigpy.trace import read_excluded
from kconfigpy.verify import read_config

KCONFIG = """\
config SMBUS_CTRL
\tbool "controller"
\tdepends on I2C
\tselect SMBUS_LIB

config SMBUS_LIB
\tbool "library"

config I2C
\tbool "i2c"

config EITHER
\tbool "either"
\tdepends on SMBUS_CTRL || FALLBACK

config FALLBACK
\tbool "fallback"

config KEPT
\tbool "kept"
"""


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    (tmp_path / "Kconfig").write_text(KCONFIG, encoding="utf-8")
    return tmp_path


def test_excluded_symbol_is_not_enabled_and_neither_is_what_it_selects_or_needs(tree: Path) -> None:
    solver = Solver(read_kconfig(tree))
    solver.exclude("SMBUS_CTRL", "no use on a headless bridge")
    solver.want("SMBUS_CTRL", "device uses it")
    solver.want("KEPT", "device uses it")
    solution = solver.solution
    assert list(solution.enabled) == ["KEPT"], "SMBUS_LIB (selected) and I2C (needed) must not follow"
    assert solution.excluded["SMBUS_CTRL"] == "no use on a headless bridge; wanted: device uses it"
    assert solution.conflicts == []


def test_either_or_dependency_takes_the_branch_that_is_not_excluded(tree: Path) -> None:
    solver = Solver(read_kconfig(tree))
    solver.exclude("SMBUS_CTRL", "excluded")
    solver.want("EITHER", "test")
    assert "FALLBACK" in solver.solution.enabled
    assert "SMBUS_CTRL" not in solver.solution.excluded, "it was never wanted, so it is not reported"


def test_exclude_file_accepts_comments_and_the_config_prefix(tmp_path: Path) -> None:
    path = tmp_path / "exclude.list"
    path.write_text("# why\nI2C_I801\nCONFIG_SPI  # flash\n\n", encoding="utf-8")
    assert read_excluded(path) == {"I2C_I801": "listed in exclude.list", "SPI": "listed in exclude.list"}


def test_generate_with_exclude_keeps_it_out_of_the_fragment_and_names_it_in_the_report(tree: Path) -> None:
    (tree / "drivers").mkdir()
    (tree / "drivers" / "Makefile").write_text("obj-$(CONFIG_SMBUS_CTRL) += smbus_ctrl.o\n", encoding="utf-8")
    (tree / "Makefile").write_text("obj-y += drivers/\n", encoding="utf-8")
    snapshot = tree / "snap.tsv"
    snapshot.write_text("dev\tpci/0\tpci:v1d2\tsmbus_ctrl\tsmbus_ctrl\n", encoding="utf-8")
    exclude = tree / "exclude.list"
    exclude.write_text("SMBUS_CTRL\n", encoding="utf-8")
    out = tree / "out"
    plain = ["generate", "--tree", str(tree), "--snapshot", str(snapshot), "--out", str(out)]
    assert main(plain) == 0
    assert read_config(out / "hardware.config").get("SMBUS_LIB") == "y", "without the list the select is followed"
    assert main([*plain, "--exclude", str(exclude)]) == 0
    assert read_config(out / "hardware.config") == {}
    assert "## Excluded on request (1)" in (out / "report.md").read_text(encoding="utf-8")
