"""kc.choice: a choice is exactly one member on, and its own default is known."""

from __future__ import annotations

from pathlib import Path

import pytest

from kconfigpy.kconfig import KconfigDb, Sym, read_kconfig
from kconfigpy.solve import Solver

KCONFIG = """\
choice SCHED
\tprompt "scheduler"
\tdefault SCHED_B if ADVANCED
\tdefault SCHED_A
\toptional
\tdepends on BASE

config SCHED_A
\tbool "a"

config SCHED_B
\tbool "b"

config SCHED_C
\tbool "c"
\tdepends on EXTRA

endchoice

config BASE
\tbool "base"

config EXTRA
\tbool "extra"

config OUTSIDE
\tbool "outside the choice"

config PICKS_B
\tbool "picks b"
\tselect SCHED_B
"""


@pytest.fixture
def db(tmp_path: Path) -> KconfigDb:
    (tmp_path / "Kconfig").write_text(KCONFIG, encoding="utf-8")
    return read_kconfig(tmp_path)


def test_reader_records_the_members_and_the_default_of_a_choice(db: KconfigDb) -> None:
    (choice,) = db.choices
    assert choice.name == "SCHED" and choice.optional
    assert choice.members == ["SCHED_A", "SCHED_B", "SCHED_C"]
    assert choice.defaults == [("SCHED_B", Sym("ADVANCED")), ("SCHED_A", None)]
    member = db.preferred("SCHED_A")
    assert member is not None and member.choice is choice
    outside = db.preferred("OUTSIDE")
    assert outside is not None and outside.choice is None


def test_two_members_are_a_conflict_naming_both_reasons(db: KconfigDb) -> None:
    solver = Solver(db)
    solver.want("SCHED_A", "device one")
    solver.want("SCHED_B", "device two")
    solution = solver.solution
    assert "SCHED_B" not in solution.enabled
    (conflict,) = solution.conflicts
    assert "SCHED_B and SCHED_A are both members of the choice" in conflict
    assert "SCHED_B is wanted (device two)" in conflict and "SCHED_A is on (device one)" in conflict


def test_a_member_chosen_twice_is_not_a_conflict_with_itself(db: KconfigDb) -> None:
    solver = Solver(db)
    solver.want("SCHED_A", "device one")
    solver.want("SCHED_A", "device two")
    assert solver.solution.conflicts == []


def test_a_select_of_a_second_member_is_a_conflict_too(db: KconfigDb) -> None:
    solver = Solver(db)
    solver.want("SCHED_A", "device one")
    solver.want("PICKS_B", "device two")
    assert any("SCHED_B and SCHED_A" in c for c in solver.solution.conflicts)


def test_a_choice_member_and_an_unrelated_option_can_both_be_on(db: KconfigDb) -> None:
    solver = Solver(db)
    solver.want("SCHED_A", "device one")
    solver.want("OUTSIDE", "device two")
    assert solver.solution.conflicts == []
    assert {"SCHED_A", "OUTSIDE"} <= set(solver.solution.enabled)
