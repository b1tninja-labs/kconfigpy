"""The snapshot module reads a sysfs tree and the module list, and writes the records trace reads back.

Linux only: sysfs names contain colons and the fixtures use symlinks, which Windows does not allow here.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from kconfexplain import snapshot
from kconfexplain.__main__ import main
from kconfexplain.trace import read_snapshot


pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="sysfs layout needs Linux")


def _fake_machine(root: Path) -> tuple[Path, Path]:
    sysfs = root / "devices"
    dev = sysfs / "pci0000:00" / "0000:00:1f.0"
    dev.mkdir(parents=True)
    (dev / "modalias").write_text("pci:v00008086d00001f18\n", encoding="utf-8")
    drv = root / "drivers" / "my_drv"
    drv.mkdir(parents=True)
    (dev / "driver").symlink_to(drv)
    (drv / "module").symlink_to(root / "module" / "my_drv")
    (root / "module" / "my_drv").mkdir(parents=True)
    modules = root / "modules"
    modules.write_text("my_drv 16384 0 - Live 0x0\nother 4096 0 - Live 0x0\n", encoding="utf-8")
    return sysfs, modules


def test_records_name_the_device_driver_and_module(tmp_path: Path) -> None:
    sysfs, modules = _fake_machine(tmp_path)
    lines = snapshot.records(sysfs, modules)
    assert lines[0] == "dev\tpci0000:00/0000:00:1f.0\tpci:v00008086d00001f18\tmy_drv\tmy_drv"
    assert lines[1:] == ["mod\tmy_drv", "mod\tother"]


def test_records_round_trip_through_read_snapshot(tmp_path: Path) -> None:
    sysfs, modules = _fake_machine(tmp_path)
    path = tmp_path / "snap.tsv"
    path.write_text("\n".join(snapshot.records(sysfs, modules)) + "\n", encoding="utf-8")
    parsed = read_snapshot(path)
    assert parsed.devices[0].driver == "my_drv"
    assert parsed.loaded == ["my_drv", "other"]


def test_missing_modules_file_is_not_an_error(tmp_path: Path) -> None:
    sysfs, _ = _fake_machine(tmp_path)
    assert snapshot.records(sysfs, tmp_path / "absent") == snapshot.records(sysfs, tmp_path / "absent")
    assert all(not line.startswith("mod") for line in snapshot.records(sysfs, tmp_path / "absent"))


def test_snapshot_command_writes_a_file(tmp_path: Path, monkeypatch) -> None:
    sysfs, modules = _fake_machine(tmp_path)
    monkeypatch.setattr(snapshot, "SYSFS", sysfs)
    monkeypatch.setattr(snapshot, "MODULES", modules)
    out = tmp_path / "out" / "snap.tsv"
    assert main(["snapshot", "--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8").startswith("dev\t")
