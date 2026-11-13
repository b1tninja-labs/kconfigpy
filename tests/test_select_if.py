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

config NEEDS_BIG
\tbool "needs big"
\tdepends on !TINY
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
        "selected by OWNER only if NET, which the requested options do not decide"
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


def test_absence_from_the_request_does_not_prove_an_option_is_off(tree: Path) -> None:
    # TINY is never mentioned. A default or another fragment may still turn it on, so "!TINY" is undecided.
    solver = Solver(read_kconfig(tree))
    solver.want("OWNER", "test")
    assert "UNLESS_TINY" not in solver.solution.enabled
    assert solver.solution.conditional["UNLESS_TINY"] == (
        "selected by OWNER only if !TINY, which the requested options do not decide"
    )


def test_negated_condition_holds_only_when_the_request_requires_the_option_off(tree: Path) -> None:
    off = Solver(read_kconfig(tree))
    off.want("OWNER", "test")
    off.want("NEEDS_BIG", "test")  # depends on !TINY, so the request itself keeps TINY off
    assert off.solution.enabled["UNLESS_TINY"] == "selected by OWNER if !TINY"

    on = Solver(read_kconfig(tree))
    on.want("OWNER", "test")
    on.want("TINY", "test")  # requested after the owner: the select must still not fire
    assert "UNLESS_TINY" not in on.solution.enabled
    assert on.solution.conditional["UNLESS_TINY"].endswith("which the requested options rule out")


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
    assert "## Conditional select not followed (4)" in report
    assert "- `WHEN_NET`: selected by OWNER only if NET" in report


def test_show_writes_an_expression_back_as_kconfig_text() -> None:
    assert show(And(Sym("A"), Not(Sym("B")))) == "A && !B"
