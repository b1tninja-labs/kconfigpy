"""kc.defaults: default and def_bool keep their values and conditions; a promptless symbol is predicted from them."""

from __future__ import annotations

from pathlib import Path

import pytest

from kconfigpy.kconfig import And, Const, KconfigDb, Not, Or, Sym, read_kconfig
from kconfigpy.solve import Solver
from kconfigpy.trace import Device, Snapshot, report_text, trace

KCONFIG = """\
config WANTED
\tbool "wanted"
\tdepends on ALWAYS_ON && NEVER_ON && COND_ON && FIRST_WINS && SECOND_WINS && FROM_SYMBOL
\tselect SELECTED_DESPITE_N

config SELECTED_DESPITE_N
\tbool
\tdefault n

config ALWAYS_ON
\tdef_bool y

config NEVER_ON
\tbool
\tdefault n

config COND_ON
\tbool
\tdefault y if SWITCH

config FIRST_WINS
\tbool
\tdefault y if ON_ONE
\tdefault n

config SECOND_WINS
\tbool
\tdefault y if OFF_ONE
\tdefault y if ON_ONE
\tdefault n

config GATED_OFF
\tdef_bool y
\tdepends on SWITCH

config FROM_SYMBOL
\tbool
\tdefault ON_ONE && !OFF_ONE

config SWITCH
\tbool "switch"

config ON_ONE
\tbool "on one"

config OFF_ONE
\tbool "off one"
"""


@pytest.fixture
def db(tmp_path: Path) -> KconfigDb:
    (tmp_path / "Kconfig").write_text(KCONFIG, encoding="utf-8")
    return read_kconfig(tmp_path)


def test_reader_keeps_each_default_value_with_its_condition_in_order(db: KconfigDb) -> None:
    second = db.preferred("SECOND_WINS")
    assert second is not None
    assert second.defaults == [(Const("y"), Sym("OFF_ONE")), (Const("y"), Sym("ON_ONE")), (Const("n"), None)]
    assert db.preferred("ALWAYS_ON").defaults == [(Const("y"), None)]  # type: ignore[union-attr]
    assert db.preferred("FROM_SYMBOL").defaults[0][0] == And(Sym("ON_ONE"), Not(Sym("OFF_ONE")))  # type: ignore[union-attr]


def test_a_value_with_a_compound_expression_is_split_on_the_top_level_if(tmp_path: Path) -> None:
    text = "config A\n\tbool\n\tdefault (B || C) && D if E || F\n"
    (tmp_path / "Kconfig").write_text(text, encoding="utf-8")
    default = read_kconfig(tmp_path).preferred("A").defaults[0]  # type: ignore[union-attr]
    assert default == (And(Or(Sym("B"), Sym("C")), Sym("D")), Or(Sym("E"), Sym("F")))


def _solve(db: KconfigDb, *requests: str) -> Solver:
    solver = Solver(db)
    for name in ("WANTED", *requests):
        solver.want(name, "test")
    return solver


def test_an_unconditional_default_y_predicts_a_promptless_symbol_on(db: KconfigDb) -> None:
    solution = _solve(db).solution
    assert solution.default_on["ALWAYS_ON"] == "first visible default y"


def test_default_n_or_no_applicable_default_predicts_off(db: KconfigDb) -> None:
    solution = _solve(db).solution
    assert solution.default_off["NEVER_ON"] == "first visible default n"


def test_a_followed_select_beats_a_default_n(db: KconfigDb) -> None:
    solution = _solve(db).solution
    assert solution.default_on["SELECTED_DESPITE_N"] == "selected by WANTED"
    assert "SELECTED_DESPITE_N" not in solution.default_off


def test_a_condition_the_request_does_not_decide_leaves_the_symbol_unpredicted(db: KconfigDb) -> None:
    solution = _solve(db).solution
    assert "COND_ON" in solution.assumed
    assert "COND_ON" not in solution.default_on and "COND_ON" not in solution.default_off


def test_a_condition_the_request_makes_true_predicts_on_in_any_order(db: KconfigDb) -> None:
    for order in (("WANTED", "SWITCH"), ("SWITCH", "WANTED")):
        solver = Solver(db)
        for name in order:
            solver.want(name, "test")
        assert solver.solution.default_on["COND_ON"] == "first visible default y if SWITCH", order


def test_the_first_visible_default_wins(db: KconfigDb) -> None:
    solution = _solve(db, "ON_ONE").solution
    assert solution.default_on["FIRST_WINS"] == "first visible default y if ON_ONE"


def test_an_earlier_default_the_request_does_not_decide_blocks_the_later_one(db: KconfigDb) -> None:
    # SECOND_WINS lists "default y if OFF_ONE" first. Nothing says OFF_ONE is off, so which default wins is open.
    solution = _solve(db).solution
    assert "SECOND_WINS" not in solution.default_on and "SECOND_WINS" not in solution.default_off


def test_unmet_dependencies_override_a_default(db: KconfigDb) -> None:
    solver = Solver(db)
    assert solver.default_of("GATED_OFF") == (None, "default y is not decided by the requested options")
    solver.forbid(Sym("SWITCH"), "test")  # GATED_OFF is "def_bool y" but depends on SWITCH, which must stay off
    assert solver.default_of("GATED_OFF") == (False, "no default applies")


def test_a_default_that_is_a_symbol_expression_is_evaluated(db: KconfigDb) -> None:
    solution = _solve(db, "ON_ONE").solution
    assert "FROM_SYMBOL" not in solution.default_on, "OFF_ONE is not decided, so the value is not either"


def test_the_report_says_what_the_defaults_predict(db: KconfigDb) -> None:
    device = Device("pci/0", "pci:v1d2", "drv", "drv")
    result = trace(Snapshot([device]), db, {"drv": {"WANTED"}}, [])
    report = report_text(result)
    assert "- `ALWAYS_ON`: dependency of WANTED; predicted on: first visible default y" in report
    assert "- `NEVER_ON`: dependency of WANTED; predicted off: first visible default n" in report
    assert "- `COND_ON`: dependency of WANTED\n" in report
    assert "- `SELECTED_DESPITE_N`: selected by WANTED; predicted on: selected by WANTED" in report
