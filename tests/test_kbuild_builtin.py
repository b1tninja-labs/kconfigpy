"""With CONFIG_MODULES off, drivers map to built-in symbols, and the report says so (fwd.builtin).

``builtin_map(...).statement`` is the line the report must carry. These tests fail if the statement is
dropped or stops naming CONFIG_MODULES. They cannot see the rendered report: trace.report_text does not
yet include the statement, and a test of the report belongs next to that wiring.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kconfigpy.kbuild import builtin_map, modules_enabled


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    (tmp_path / "drivers" / "net").mkdir(parents=True)
    (tmp_path / "drivers" / "net" / "Makefile").write_text(
        "obj-$(CONFIG_DRV) += my-drv.o\nobj-$(CONFIG_OTHER) += other.o\n", encoding="utf-8"
    )
    return tmp_path


def write_config(tmp_path: Path, body: str) -> Path:
    config = tmp_path / ".config"
    config.write_text(body, encoding="utf-8")
    return config


def test_modules_off_maps_driver_to_builtin_symbol(tree: Path) -> None:
    config = write_config(tree, "CONFIG_PCI=y\n# CONFIG_MODULES is not set\n")
    result = builtin_map(config, tree, {"my_drv", "absent"})
    assert result.modules_enabled is False
    assert result.drivers == {"my_drv": {"DRV"}}


def test_statement_says_modules_are_off_and_names_the_drivers(tree: Path) -> None:
    config = write_config(tree, "# CONFIG_MODULES is not set\n")
    statement = builtin_map(config, tree, {"my_drv", "absent"}).statement
    assert "CONFIG_MODULES is off" in statement
    assert "1 driver(s) are mapped to built-in symbols" in statement
    assert "absent" in statement
    assert "\n" not in statement


def test_absent_modules_line_counts_as_off(tree: Path) -> None:
    config = write_config(tree, "CONFIG_PCI=y\n")
    assert modules_enabled(config) is False


def test_modules_on_maps_nothing(tree: Path) -> None:
    config = write_config(tree, "CONFIG_MODULES=y\n")
    result = builtin_map(config, tree, {"my_drv"})
    assert result.modules_enabled is True
    assert result.drivers == {}
    assert "CONFIG_MODULES is on" in result.statement
