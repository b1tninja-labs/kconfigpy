"""``generate --built-tree`` takes aliases and the modules-off mapping from a build output directory.

These cover the wiring of fwd.modalias and fwd.builtin: the library functions are tested elsewhere.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kconfigpy.__main__ import main
from kconfigpy.verify import read_config

KCONFIG = 'mainmenu "T"\n\nconfig DRV\n\ttristate "Driver"\n\nconfig OTHER\n\ttristate "Other"\n'
UNBOUND = "dev\tpci/0\tpci:v1d2\t\t\n"
BOUND = "dev\tpci/0\tpci:v1d2\tmy-drv\t\n"


@pytest.fixture
def source(tmp_path: Path) -> Path:
    tree = tmp_path / "src"
    (tree / "drivers").mkdir(parents=True)
    (tree / "Kconfig").write_text(KCONFIG, encoding="utf-8")
    (tree / "drivers" / "Makefile").write_text(
        "obj-$(CONFIG_DRV) += my-drv.o\nobj-$(CONFIG_OTHER) += other.o\n", encoding="utf-8"
    )
    return tree


def built(tmp_path: Path, config: str, aliases: bool = True) -> Path:
    out = tmp_path / "build"
    out.mkdir()
    (out / ".config").write_text(config, encoding="utf-8")
    if aliases:
        (out / "modules.alias").write_text("alias pci:v1d2* my_drv\n", encoding="utf-8")
        (out / "modules.builtin.alias").write_text("", encoding="utf-8")
    return out


def run(source: Path, build: Path, tmp_path: Path, snapshot: str) -> tuple[int, str]:
    snap = tmp_path / "snap.tsv"
    snap.write_text(snapshot, encoding="utf-8")
    out = tmp_path / "out"
    code = main(
        ["generate", "--tree", str(source), "--snapshot", str(snap), "--built-tree", str(build), "--out", str(out)]
    )
    report = out / "report.md"
    return code, report.read_text(encoding="utf-8") if report.exists() else ""


def test_aliases_come_from_the_built_tree(source: Path, tmp_path: Path) -> None:
    code, report = run(source, built(tmp_path, "CONFIG_MODULES=y\n"), tmp_path, UNBOUND)
    assert code == 0
    assert "## Available devices (1)" in report
    assert "`pci:v1d2`: my_drv -> DRV" in report
    assert "modules are off" not in report


def test_modules_off_is_reported_and_drivers_are_mapped(source: Path, tmp_path: Path) -> None:
    code, report = run(source, built(tmp_path, "# CONFIG_MODULES is not set\n"), tmp_path, BOUND)
    assert code == 0
    assert "modules are off: drivers mapped to built-in symbols" in report
    assert "CONFIG_MODULES is off" in report
    assert "my_drv" in report
    assert read_config(tmp_path / "out" / "hardware.config")["DRV"] == "y"


def test_missing_alias_file_is_refused_by_name(
    source: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _ = run(source, built(tmp_path, "CONFIG_MODULES=y\n", aliases=False), tmp_path, UNBOUND)
    assert code == 2
    assert "modules.alias" in capsys.readouterr().err
    assert not (tmp_path / "out" / "hardware.config").exists()


def test_missing_config_is_refused_by_name(source: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    build = built(tmp_path, "")
    (build / ".config").unlink()
    code, _ = run(source, build, tmp_path, UNBOUND)
    assert code == 2
    assert ".config" in capsys.readouterr().err


def test_aliases_option_still_works(source: Path, tmp_path: Path) -> None:
    aliases = tmp_path / "a"
    aliases.write_text("alias pci:v1d2* my_drv\n", encoding="utf-8")
    snap = tmp_path / "snap.tsv"
    snap.write_text(UNBOUND, encoding="utf-8")
    out = tmp_path / "out"
    args = ["trace", "--tree", str(source), "--snapshot", str(snap), "--aliases", str(aliases), "--out", str(out)]
    assert main(args) == 0
    assert "`pci:v1d2`: my_drv -> DRV" in (out / "report.md").read_text(encoding="utf-8")
