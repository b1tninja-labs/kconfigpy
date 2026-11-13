"""``select`` chains: a selected option carries a reason, and one whose own dependencies are unmet is forced."""

from __future__ import annotations

from pathlib import Path

import pytest

from kconfigpy.kconfig import read_kconfig
from kconfigpy.solve import Solver
from kconfigpy.trace import Device, Snapshot, fragment_text, report_text, trace

KCONFIG = """\
mainmenu "Select"

config SEL_TOP
\tbool "Top"
\tselect SEL_OK
\tselect SEL_BAD

config SEL_OK
\tbool "Ok"
\tselect SEL_CHAIN

config SEL_CHAIN
\tbool "Chain"

config SEL_BAD
\tbool "Bad"
\tdepends on !SEL_TOP
"""


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    (tmp_path / "Kconfig").write_text(KCONFIG, encoding="utf-8")
    return tmp_path


def test_select_chain_is_followed_and_each_option_has_a_reason(tree: Path) -> None:
    solver = Solver(read_kconfig(tree))
    solver.want("SEL_TOP", "test")
    enabled = solver.solution.enabled
    assert enabled["SEL_OK"] == "selected by SEL_TOP"
    assert enabled["SEL_CHAIN"] == "selected by SEL_OK"


def test_select_forced_option_with_unmet_dependency_is_forced_not_solved(tree: Path) -> None:
    solver = Solver(read_kconfig(tree))
    solver.want("SEL_TOP", "test")
    solution = solver.solution
    # SEL_BAD depends on !SEL_TOP, which is on: the select still turns it on, so it is forced.
    assert "SEL_BAD" not in solution.enabled
    assert "SEL_BAD" in solution.forced
    assert "selected by SEL_TOP" in solution.forced["SEL_BAD"]
    assert any("SEL_BAD" in c for c in solution.conflicts)


def test_forced_option_is_left_out_of_the_fragment_and_named_in_the_report(tree: Path) -> None:
    device = Device("pci/0", "pci:v1d2", "sel", "sel")
    result = trace(Snapshot([device]), read_kconfig(tree), {"sel": {"SEL_TOP"}}, [])
    assert "CONFIG_SEL_OK=y" in fragment_text(result)
    assert "CONFIG_SEL_BAD" not in fragment_text(result)
    report = report_text(result)
    assert "## Forced by select, dependencies unmet (1)" in report
    assert "- `SEL_BAD`: selected by SEL_TOP" in report
