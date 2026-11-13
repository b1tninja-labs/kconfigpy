"""``verify`` matches each fragment line verbatim against the resolved config."""

from __future__ import annotations

from pathlib import Path

from kconfigpy.kconfig import KconfigDb
from kconfigpy.verify import read_exact, verify


def _verify(requested: dict[str, str], resolved: dict[str, str]):
    return verify(requested, resolved, KconfigDb())


def test_nr_cpus_1_is_not_accepted_for_nr_cpus_128() -> None:
    outcome = _verify({"NR_CPUS": "1"}, {"NR_CPUS": "128"})
    assert outcome.kept == []
    assert "NR_CPUS" in outcome.dropped


def test_identical_value_is_kept() -> None:
    assert _verify({"NR_CPUS": "128"}, {"NR_CPUS": "128"}).kept == ["NR_CPUS"]


def test_module_is_not_built_in() -> None:
    assert _verify({"DRV": "y"}, {"DRV": "m"}).dropped.keys() == {"DRV"}


def test_value_is_not_prefix_or_substring_matched() -> None:
    for want, got in [("12", "128"), ("28", "128"), ('"a"', '"ab"'), ("y", "yes")]:
        assert _verify({"X": want}, {"X": got}).kept == []


def test_disable_line_is_exact(tmp_path: Path) -> None:
    fragment = tmp_path / "f"
    fragment.write_text("# CONFIG_A is not set\n# CONFIG_B is not set\nCONFIG_C=y\n", encoding="utf-8")
    requested = read_exact(fragment)
    assert requested == {"A": "n", "B": "n", "C": "y"}
    outcome = _verify(requested, {"A": "y", "C": "y"})
    assert outcome.kept == ["B", "C"]
    assert list(outcome.dropped) == ["A"]


def test_explicit_not_set_in_resolved_config_meets_a_disable(tmp_path: Path) -> None:
    config = tmp_path / ".config"
    config.write_text("# CONFIG_A is not set\n", encoding="utf-8")
    assert _verify({"A": "n"}, read_exact(config)).kept == ["A"]
