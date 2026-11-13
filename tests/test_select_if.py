"""``select X if <expr>``: the condition is kept, and the select is followed only when the request meets it."""

from __future__ import annotations

from pathlib import Path

import pytest

from kconfigpy.kconfig import And, Not, Sym, read_kconfig, show
from kconfigpy.solve import Solver
from kconfigpy.trace import Device, Snapshot, fragment_text, report_text, trace

KCONFIG = """\
config OWNER
\tbool "owner"
\tselect ALWAYS
\tselect WHEN_NET if NET
\tselect UNLESS_TINY if !TINY
\tselect PROBED if $(cc-option,-fx)
\tselect BOTH if NET && EXTRA

config ALWAYS
\tbool "always"

config WHEN_NET
\tbool "when net"
\tselect CHAINED

config CHAINED
\tbool "chained"

config UNLESS_TINY
\tbool "unless tiny"

config PROBED
\tbool "probed"

config BOTH
\tbool "both"

config NET
\tbool "net"

config EXTRA
\tbool "extra"

config TINY
\tbool "tiny"
"""


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    (tmp_path / "Kconfig").write_text(KCONFIG, encoding="utf-8")
    return tmp_path


def test_reader_keeps_the_condition_apart_from_plain_selects(tree: Path) -> None:
    owner = read_kconfig(tree).preferred("OWNER")
    assert owner is not None
    assert owner.selects == ["ALWAYS"]
    assert ("WHEN_NET", Sym("NET")) in owner.select_if
    assert ("BOTH", And(Sym("NET"), Sym("EXTRA"))) in owner.select_if


def test_unmet_condition_is_not_followed_and_says_why(tree: Path) -> None:
    solver = Solver(read_kconfig(tree))
    solver.want("OWNER", "test")
    solution = solver.solution
    assert "ALWAYS" in solution.enabled
    assert "WHEN_NET" not in solution.enabled and "CHAINED" not in solution.enabled
    assert solution.conditional["WHEN_NET"] == (
        "selected by OWNER only if NET, which is not met by the requested options"
    )


def test_met_condition_is_followed_whatever_the_order_of_requests(tree: Path) -> None:
    for order in (("OWNER", "NET"), ("NET", "OWNER")):
        solver = Solver(read_kconfig(tree))
        for name in order:
            solver.want(name, "test")
        enabled = solver.solution.enabled
        assert enabled["WHEN_NET"] == "selected by OWNER if NET", order
        assert enabled["CHAINED"] == "selected by WHEN_NET", order
        assert "WHEN_NET" not in solver.solution.conditional


def test_every_term_of_the_condition_must_hold(tree: Path) -> None:
    solver = Solver(read_kconfig(tree))
    solver.want("OWNER", "test")
    solver.want("NET", "test")
    assert "BOTH" not in solver.solution.enabled
    solver.want("EXTRA", "test")
    assert solver.solution.enabled["BOTH"] == "selected by OWNER if NET && EXTRA"


def test_negated_condition_is_judged_against_everything_requested(tree: Path) -> None:
    alone = Solver(read_kconfig(tree))
    alone.want("OWNER", "test")
    assert alone.solution.enabled["UNLESS_TINY"] == "selected by OWNER if !TINY"

    with_tiny = Solver(read_kconfig(tree))
    with_tiny.want("OWNER", "test")
    with_tiny.want("TINY", "test")  # requested after the owner: the select must still not fire
    assert "UNLESS_TINY" not in with_tiny.solution.enabled
    assert "which is not met" in with_tiny.solution.conditional["UNLESS_TINY"]


def test_condition_that_cannot_be_evaluated_is_not_followed_and_is_reported(tree: Path) -> None:
    solver = Solver(read_kconfig(tree))
    solver.want("OWNER", "test")
    assert "PROBED" not in solver.solution.enabled
    assert solver.solution.conditional["PROBED"].endswith("which is not evaluated")


def test_fragment_leaves_it_out_and_the_report_names_it(tree: Path) -> None:
    device = Device("pci/0", "pci:v1d2", "drv", "drv")
    result = trace(Snapshot([device]), read_kconfig(tree), {"drv": {"OWNER"}}, [])
    fragment = fragment_text(result)
    assert "CONFIG_ALWAYS=y" in fragment
    assert "CONFIG_WHEN_NET" not in fragment
    report = report_text(result)
    assert "## Conditional select not followed (3)" in report
    assert "- `WHEN_NET`: selected by OWNER only if NET" in report


def test_show_writes_an_expression_back_as_kconfig_text() -> None:
    assert show(And(Sym("A"), Not(Sym("B")))) == "A && !B"
