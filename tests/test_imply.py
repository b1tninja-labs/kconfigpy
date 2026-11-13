"""kc.imply: an implied option is reported as likely on, with the implying option as the reason."""

from __future__ import annotations

from pathlib import Path

import pytest

from kconfigpy.kconfig import KconfigDb, Sym, read_kconfig
from kconfigpy.solve import Solver
from kconfigpy.trace import Device, Snapshot, fragment_text, report_text, trace

KCONFIG = """\
config OWNER
\tbool "owner"
\timply FREE
\timply NEEDS_NET
\timply NEEDS_BLOCKED
\timply ONLY_WITH_FLAG if FLAG
\timply GHOST

config FREE
\ttristate "free"

config NEEDS_NET
\ttristate "needs net"
\tdepends on NET

config NEEDS_BLOCKED
\ttristate "needs blocked"
\tdepends on BLOCKED

config ONLY_WITH_FLAG
\ttristate "only with flag"

config NET
\tbool "net"

config BLOCKED
\tbool "blocked"

config FLAG
\tbool "flag"
"""


@pytest.fixture
def db(tmp_path: Path) -> KconfigDb:
    (tmp_path / "Kconfig").write_text(KCONFIG, encoding="utf-8")
    return read_kconfig(tmp_path)


def test_reader_records_imply_apart_from_select(db: KconfigDb) -> None:
    owner = db.preferred("OWNER")
    assert owner is not None
    assert owner.selects == []
    assert ("FREE", None) in owner.implies
    assert ("ONLY_WITH_FLAG", Sym("FLAG")) in owner.implies


def test_an_implied_option_with_no_dependencies_is_likely_on_and_names_its_owner(db: KconfigDb) -> None:
    solver = Solver(db)
    solver.want("OWNER", "test")
    solution = solver.solution
    assert solution.implied["FREE"] == "implied by OWNER, and its dependencies hold"
    assert "FREE" not in solution.enabled, "imply is a hint about the resolved config, never a request"


def test_imply_obeys_the_direct_dependencies_of_the_target(db: KconfigDb) -> None:
    solver = Solver(db)
    solver.want("OWNER", "test")
    assert "NEEDS_NET" not in solver.solution.implied
    assert solver.solution.implied_off["NEEDS_NET"].endswith("but its dependencies (NET) are not decided")
    solver.want("NET", "test")
    assert solver.solution.implied["NEEDS_NET"] == "implied by OWNER, and its dependencies hold"
    assert "NEEDS_NET" not in solver.solution.implied_off


def test_a_dependency_the_request_rules_out_stops_the_imply(db: KconfigDb) -> None:
    solver = Solver(db)
    solver.forbid(Sym("BLOCKED"), "test")
    solver.want("OWNER", "test")
    assert solver.solution.implied_off["NEEDS_BLOCKED"].endswith("its dependencies (BLOCKED) do not hold")


def test_a_condition_on_the_imply_must_hold_too(db: KconfigDb) -> None:
    solver = Solver(db)
    solver.want("OWNER", "test")
    assert solver.solution.implied_off["ONLY_WITH_FLAG"].endswith("the condition is not decided by the request")
    solver.want("FLAG", "test")
    assert solver.solution.implied["ONLY_WITH_FLAG"] == "implied by OWNER if FLAG, and its dependencies hold"


def test_an_undefined_target_is_reported_not_guessed(db: KconfigDb) -> None:
    solver = Solver(db)
    solver.want("OWNER", "test")
    assert solver.solution.implied_off["GHOST"].endswith("but it is not defined")


def test_an_option_that_is_both_requested_and_implied_is_just_requested(db: KconfigDb) -> None:
    solver = Solver(db)
    solver.want("OWNER", "test")
    solver.want("FREE", "device")
    assert "FREE" not in solver.solution.implied
    assert solver.solution.enabled["FREE"] == "device"


def test_an_excluded_target_is_not_likely_on(db: KconfigDb) -> None:
    solver = Solver(db)
    solver.exclude("FREE", "listed")
    solver.want("OWNER", "test")
    assert solver.solution.implied_off["FREE"].endswith("but it is excluded (listed)")


def test_the_report_lists_implied_options_and_the_fragment_leaves_them_out(db: KconfigDb) -> None:
    device = Device("pci/0", "pci:v1d2", "drv", "drv")
    result = trace(Snapshot([device]), db, {"drv": {"OWNER"}}, [])
    assert "CONFIG_FREE" not in fragment_text(result)
    report = report_text(result)
    assert "## Implied, likely on (1)" in report
    assert "- `FREE`: implied by OWNER, and its dependencies hold" in report
    assert "## Implied, not known to take effect (4)" in report
