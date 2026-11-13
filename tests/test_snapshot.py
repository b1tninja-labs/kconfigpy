"""The snapshot module reads a sysfs tree and the module list, and writes the records trace reads back.

Linux only: sysfs names contain colons and the fixtures use symlinks, which Windows does not allow here.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from kconfigpy import snapshot
from kconfigpy.__main__ import main
from kconfigpy.trace import read_snapshot


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
    lines = snapshot.records(sysfs, modules, log=lambda: "")
    assert lines[0] == "dev\tpci0000:00/0000:00:1f.0\tpci:v00008086d00001f18\tmy_drv\tmy_drv"
    assert [line for line in lines if line.startswith("mod	")] == ["mod\tmy_drv", "mod\tother"]


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


def test_snapshot_command_writes_a_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sysfs, modules = _fake_machine(tmp_path)
    monkeypatch.setattr(snapshot, "SYSFS", sysfs)
    monkeypatch.setattr(snapshot, "MODULES", modules)
    out = tmp_path / "out" / "snap.tsv"
    assert main(["snapshot", "--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8").startswith("dev\t")


def test_local_snapshot_is_refused_off_linux(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    with pytest.raises(NotImplementedError, match="Use --ssh HOST"):
        snapshot.records(tmp_path, tmp_path / "modules")


def test_empty_sysfs_is_refused_not_written(tmp_path: Path) -> None:
    if sys.platform != "linux":
        pytest.skip("linux only")
    empty = tmp_path / "devices"
    empty.mkdir()
    with pytest.raises(RuntimeError, match="refusing to write an empty snapshot"):
        snapshot.records(empty, tmp_path / "modules")


def _unbound_machine(root: Path) -> tuple[Path, Path, Path]:
    """A fake machine with one device that has no driver, a ``going`` module and a module alias table."""
    sysfs, modules = _fake_machine(root)
    orphan = sysfs / "pci0000:00" / "0000:00:02.0"
    orphan.mkdir()
    (orphan / "modalias").write_text("pci:v00001234d00005678sv00000000sd00000000bc03sc00i00\n", encoding="utf-8")
    for name, state in (("my_drv", "live"), ("fading", "going"), ("builtin", None)):
        entry = root / "module" / name
        entry.mkdir(exist_ok=True)
        if state:
            (entry / "initstate").write_text(state + "\n", encoding="utf-8")
    aliases = root / "modules.alias"
    aliases.write_text(
        "# comment\n"
        "alias pci:v00001234d0000*sv*sd*bc*sc*i* ondemand-drv\n"
        "alias pci:v00009999d* nomatch\n"
        "alias pci:v00008086d00001f18* my_drv\n",
        encoding="utf-8",
    )
    return sysfs, modules, aliases


_LOG = (
    "[    1.2] vendor_blob: loading out-of-tree module taints kernel.\n[    1.3] my_drv: module verification failed\n"
)


def test_boot_only_modules_are_recorded_as_seen(tmp_path: Path) -> None:
    sysfs, modules, aliases = _unbound_machine(tmp_path)
    lines = snapshot.records(sysfs, modules, aliases=aliases, log=lambda: _LOG)
    seen = [line.split("\t") for line in lines if line.startswith("seen\t")]
    assert ["seen", "fading", "sysmodule", "going"] in seen
    assert ["seen", "ondemand_drv", "alias", "pci0000:00/0000:00:02.0"] in seen
    assert any(row[:3] == ["seen", "vendor_blob", "dmesg"] for row in seen)
    names = {row[1] for row in seen}
    assert "my_drv" not in names, "a module that is loaded now is not boot-only"
    assert "builtin" not in names and "nomatch" not in names


def test_blind_records_say_what_could_not_be_seen(tmp_path: Path) -> None:
    sysfs, modules, aliases = _unbound_machine(tmp_path)
    lines = snapshot.records(sysfs, modules, aliases=tmp_path / "no-such-alias", log=lambda: None)
    blind = {line.split("\t")[1] for line in lines if line.startswith("blind\t")}
    assert {"dmesg", "modules.alias", "unbound-devices", "unlogged-unload", "absent-hardware"} <= blind
    readable = snapshot.records(sysfs, modules, aliases=aliases, log=lambda: "")
    kinds = {line.split("\t")[1] for line in readable if line.startswith("blind\t")}
    assert "unlogged-unload" in kinds
    assert not kinds & {"dmesg", "modules.alias", "unbound-devices"}


def test_new_records_do_not_disturb_read_snapshot(tmp_path: Path) -> None:
    sysfs, modules, aliases = _unbound_machine(tmp_path)
    path = tmp_path / "snap.tsv"
    lines = snapshot.records(sysfs, modules, aliases=aliases, log=lambda: _LOG)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    parsed = read_snapshot(path)
    assert parsed.loaded == ["my_drv", "other"]
    assert len(parsed.devices) == 2
