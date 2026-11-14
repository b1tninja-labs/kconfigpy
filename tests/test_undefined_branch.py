"""An either/or dependency never takes a branch that names a symbol this architecture does not define."""

from __future__ import annotations

from pathlib import Path

from kconfigpy.kconfig import read_kconfig
from kconfigpy.solve import Solver

KCONFIG = """\
config PLATFORM_DRIVER
\ttristate "platform driver"
\tdepends on ARCH_OTHER || COMPILE_TEST

config GENERIC_DRIVER
\ttristate "generic driver"
\tdepends on ARCH_OTHER || HOSTED

config HOSTED
\tbool "hosted"

config COMPILE_TEST
\tbool "compile test"
"""

SELECT_FORCES = """\
config OWNER
\tbool "owner"
\tselect FORCED

config FORCED
\tbool "forced"
\tdepends on NOWHERE
"""


def _solver(tmp_path: Path, text: str = KCONFIG) -> Solver:
    (tmp_path / "Kconfig").write_text(text, encoding="utf-8")
    return Solver(read_kconfig(tmp_path))


def test_a_branch_naming_an_undefined_symbol_is_never_chosen(tmp_path: Path) -> None:
    solver = _solver(tmp_path)
    solver.want("GENERIC_DRIVER", "test")
    solution = solver.solution
    assert "HOSTED" in solution.enabled, "the defined branch is taken"
    assert "ARCH_OTHER" not in solution.enabled and "ARCH_OTHER" not in solution.assumed


def test_when_no_branch_can_hold_the_option_is_reported_not_proposed(tmp_path: Path) -> None:
    solver = _solver(tmp_path)
    solver.want("PLATFORM_DRIVER", "device uses it")
    solution = solver.solution
    # ARCH_OTHER does not exist for this architecture and COMPILE_TEST is never chosen: no branch holds.
    assert "PLATFORM_DRIVER" not in solution.enabled
    assert "ARCH_OTHER" not in solution.enabled and "COMPILE_TEST" not in solution.enabled
    assert solution.unsatisfiable["PLATFORM_DRIVER"] == (
        "device uses it; but ARCH_OTHER || COMPILE_TEST cannot hold here, so the kernel would drop it"
    )


def test_a_select_still_forces_its_target_whatever_its_dependencies_say(tmp_path: Path) -> None:
    solver = _solver(tmp_path, SELECT_FORCES)
    solver.want("OWNER", "test")
    solution = solver.solution
    assert "FORCED" in solution.forced and "FORCED" not in solution.unsatisfiable
