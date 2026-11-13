"""``verify`` tells dropped, changed and disabled apart."""

from __future__ import annotations

from pathlib import Path

from kconfigpy.kconfig import KconfigDb, read_kconfig
from kconfigpy.verify import read_exact, report, verify

KCONFIG = 'config PCI\n\tbool "pci"\n\nconfig VENDOR\n\ttristate "v"\n\tdepends on PCI\n'


def _tree(tmp_path: Path) -> KconfigDb:
    (tmp_path / "Kconfig").write_text(KCONFIG, encoding="utf-8")
    return read_kconfig(tmp_path)


def test_absent_symbol_is_dropped_with_its_blocking_dependency(tmp_path: Path) -> None:
    result = verify({"VENDOR": "y"}, {}, _tree(tmp_path))
    assert result.dropped == {"VENDOR": ["PCI"]}
    assert not result.changed and not result.disabled
    assert result.failed


def test_module_for_builtin_is_changed_not_dropped(tmp_path: Path) -> None:
    result = verify({"VENDOR": "y"}, {"PCI": "y", "VENDOR": "m"}, _tree(tmp_path))
    assert result.changed["VENDOR"].requested == "y"
    assert result.changed["VENDOR"].resolved == "m"
    assert not result.dropped and not result.disabled
    assert result.failed


def test_int_hex_and_string_values_are_compared_verbatim() -> None:
    db = KconfigDb()
    requested = {"I": "1", "H": "0x10", "S": '"a"'}
    result = verify(requested, {"I": "128", "H": "0x100", "S": '"ab"'}, db)
    assert set(result.changed) == {"I", "H", "S"}
    assert verify(requested, requested, db).kept == ["H", "I", "S"]


def test_explicit_not_set_is_disabled_with_blocking_dependency(tmp_path: Path) -> None:
    config = tmp_path / ".config"
    config.write_text("# CONFIG_PCI is not set\n# CONFIG_VENDOR is not set\n", encoding="utf-8")
    result = verify({"VENDOR": "y"}, read_exact(config), _tree(tmp_path))
    assert result.disabled == {"VENDOR": ["PCI"]}
    assert not result.dropped and not result.changed
    assert result.failed


def test_disable_request_met_by_a_value_is_changed() -> None:
    result = verify({"A": "n"}, {"A": "y"}, KconfigDb())
    assert result.changed["A"].resolved == "y"
    assert result.failed


def test_all_kept_is_not_failed_and_reports_nothing() -> None:
    result = verify({"A": "y", "B": "n"}, {"A": "y"}, KconfigDb())
    assert not result.failed
    assert report(result) == []


def test_report_names_each_outcome(tmp_path: Path) -> None:
    result = verify({"VENDOR": "y", "PCI": "y", "X": "1"}, {"PCI": "n", "X": "2"}, _tree(tmp_path))
    text = "\n".join(report(result))
    assert "disabled PCI" in text
    assert "changed X: requested 1, resolved 2" in text
    assert "dropped VENDOR: PCI" in text
