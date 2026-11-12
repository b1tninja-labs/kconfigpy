from __future__ import annotations

from pathlib import Path

import pytest

from kconfigexplain.__main__ import main
from kconfigexplain.kbuild import driver_sources, module_map
from kconfigexplain.kconfig import And, Not, Or, Sym, Unknown, parse_expr, read_kconfig
from kconfigexplain.solve import Solver
from kconfigexplain.trace import Device, Snapshot, candidates, fragment_text, trace
from kconfigexplain.verify import holds, read_config, verify

KCONFIG = """\
mainmenu "Test"

source "drivers/Kconfig"

config PCI
\tbool "PCI"
\thelp
\t  config NOT_A_SYMBOL looks like a symbol
\t  but this is help text.

config HAS_IOMEM
\tdef_bool y

config COMPILE_TEST
\tbool "Compile test"

config OPTIONAL_LIB
\tbool "Optional library"

config ALT_A
\tbool "A"

config ALT_B
\tbool "B"

config OLD_THING
\tbool "Old"
"""

DRIVERS = """\
menuconfig NETDEVICES
\tbool "Network devices"

if NETDEVICES

config VENDOR
\tbool "Vendor"
\tdepends on PCI

menu "Inner"
\tdepends on VENDOR

config DRV
\ttristate "Driver"
\tdepends on HAS_IOMEM && (OPTIONAL_LIB || !OPTIONAL_LIB)
\tdepends on ALT_A || COMPILE_TEST
\tdepends on !OLD_THING

endmenu
endif

config MOD_ONLY
\ttristate "Module only"
\tdepends on m

config HIDDEN_CHILD
\ttristate
\tdepends on VENDOR
\tdefault y
"""


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    (tmp_path / "drivers" / "net").mkdir(parents=True)
    (tmp_path / "Kconfig").write_text(KCONFIG, encoding="utf-8")
    (tmp_path / "drivers" / "Kconfig").write_text(DRIVERS, encoding="utf-8")
    (tmp_path / "drivers" / "net" / "Makefile").write_text(
        "obj-$(CONFIG_DRV) += my-drv.o \\\n\tother.o\nobj-$(CONFIG_VENDOR) += sub/\n", encoding="utf-8"
    )
    return tmp_path


def test_expression_shapes() -> None:
    assert parse_expr("A && (B || !C)") == And(Sym("A"), Or(Sym("B"), Not(Sym("C"))))
    assert parse_expr("X=n") == Not(Sym("X"))
    assert parse_expr("X != n") == Sym("X")
    assert isinstance(parse_expr("$(cc-option,-foo)"), Unknown)
    assert isinstance(parse_expr("VAL > 3"), Unknown)


def test_help_text_is_not_parsed(tree: Path) -> None:
    db = read_kconfig(tree)
    assert "NOT_A_SYMBOL" not in db.definitions
    assert {"PCI", "DRV", "NETDEVICES"} <= set(db.definitions)
    assert db.missing_sources == []


def test_module_map_joins_continuations_and_normalizes(tree: Path) -> None:
    assert module_map(tree) == {"my_drv": {"DRV"}, "other": {"DRV"}}


def test_solver_takes_full_chain_and_nothing_extra(tree: Path) -> None:
    solver = Solver(read_kconfig(tree))
    solver.want("DRV", "test")
    enabled = set(solver.solution.enabled)
    # Blocks (if, menu) contribute dependencies; optional deps are not pulled in.
    assert enabled == {"DRV", "VENDOR", "NETDEVICES", "PCI", "ALT_A"}
    assert "OLD_THING" in solver.solution.forbidden
    assert "HAS_IOMEM" in solver.solution.assumed


def test_promptless_symbol_still_enables_its_parents(tree: Path) -> None:
    solver = Solver(read_kconfig(tree))
    solver.want("HIDDEN_CHILD", "test")
    assert "HIDDEN_CHILD" in solver.solution.assumed
    assert {"VENDOR", "PCI", "NETDEVICES"} <= set(solver.solution.enabled)


def test_driver_name_resolves_through_composite_object(tree: Path) -> None:
    net = tree / "drivers" / "net"
    (net / "Makefile").write_text("obj-$(CONFIG_DRV) += my-mod.o\nmy-mod-objs := core.o\n", encoding="utf-8")
    (net / "core.c").write_text('static struct x d = {\n\t.name = "short",\n};\n', encoding="utf-8")
    assert driver_sources(tree, {"short", "absent"}) == {"short": {"DRV"}}


def test_solver_flags_module_only(tree: Path) -> None:
    solver = Solver(read_kconfig(tree))
    solver.want("MOD_ONLY", "test")
    assert any("cannot be built in" in c for c in solver.solution.conflicts)


def test_every_option_records_a_reason(tree: Path) -> None:
    device = Device("pci/0", "pci:v1d2", "my-drv", "my_drv")
    result = trace(Snapshot([device], ["my_drv", "bridge"]), read_kconfig(tree), module_map(tree), [])
    text = fragment_text(result)
    assert "# device pci:v1d2 uses driver my_drv\nCONFIG_DRV=y" in text
    assert "# dependency of DRV\nCONFIG_ALT_A=y" in text
    assert "bridge" in result.loaded_only


def test_unbound_device_is_reported_not_enabled(tree: Path) -> None:
    aliases = [("pci:v1d*", "my_drv")]
    assert candidates("pci:v1d2", aliases) == ["my_drv"]
    result = trace(Snapshot([Device("pci/0", "pci:v1d2", "", "")]), read_kconfig(tree), module_map(tree), aliases)
    assert result.rows[0].status == "available"
    assert result.solution.enabled == {}


def test_verify_names_the_blocking_dependency(tree: Path) -> None:
    db = read_kconfig(tree)
    assert holds(parse_expr("A || B"), {"A": "y"}) is True
    outcome = verify({"PCI": "y", "VENDOR": "y"}, {"NETDEVICES": "y"}, db)
    assert outcome.dropped["VENDOR"] == ["PCI"]


def test_cli_end_to_end(tree: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    snapshot = tmp_path / "snap.tsv"
    snapshot.write_text("dev\tpci/0\tpci:v1d2\tmy-drv\tmy_drv\nmod\tmy_drv\n", encoding="utf-8")
    out = tmp_path / "out"
    assert main(["trace", "--tree", str(tree), "--snapshot", str(snapshot), "--out", str(out)]) == 0
    assert read_config(out / "hardware.config")["DRV"] == "y"
    assert "uses driver my_drv" in (out / "report.md").read_text(encoding="utf-8")
    assert "options enabled: 5" in capsys.readouterr().out
