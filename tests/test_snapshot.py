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


def _rich_machine(root: Path) -> tuple[Path, Path]:
    """Platform, ACPI and USB devices with no modalias, a PCI bridge with a child, DMI, classes, /proc/devices."""
    sysfs, modules = _fake_machine(root)
    bridge = sysfs / "pci0000:00" / "0000:00:1c.0"
    bridge.mkdir()
    (bridge / "modalias").write_text("pci:v00008086d00009d10sv0sd0bc06sc04i00\n", encoding="utf-8")
    behind = bridge / "0000:01:00.0"
    behind.mkdir()
    (behind / "modalias").write_text("pci:v000010ECd00008168sv0sd0bc02sc00i00\n", encoding="utf-8")
    soc = sysfs / "platform" / "soc" / "uart@1000"
    soc.mkdir(parents=True)
    (soc / "uevent").write_text("DRIVER=serial\nOF_NAME=uart\nOF_COMPATIBLE_0=ns16550a\n", encoding="utf-8")
    acpi = sysfs / "platform" / "PNP0C0A:00"
    (acpi / "firmware_node").mkdir(parents=True)
    (acpi / "firmware_node" / "hid").write_text("PNP0C0A\n", encoding="utf-8")
    (acpi / "uevent").write_text("DRIVER=battery\n", encoding="utf-8")
    usb = sysfs / "pci0000:00" / "usb1" / "1-1"
    usb.mkdir(parents=True)
    (usb / "idVendor").write_text("046d\n", encoding="utf-8")
    (usb / "idProduct").write_text("c52b\n", encoding="utf-8")
    iface = usb / "1-1:1.0"
    iface.mkdir()
    (iface / "modalias").write_text("usb:v046DpC52Bd0000dc00dsc00dp00ic03isc01ip01in00\n", encoding="utf-8")
    (root / "class" / "dmi" / "id").mkdir(parents=True)
    for field, value in (("sys_vendor", "ACME"), ("board_name", "B1"), ("product_serial", "SECRET123")):
        (root / "class" / "dmi" / "id" / field).write_text(value + "\n", encoding="utf-8")
    net = root / "class" / "net"
    net.mkdir()
    (net / "br0").mkdir()
    (net / "eth0").mkdir()
    (net / "eth0" / "device").symlink_to(behind)
    (root / "class" / "tty").mkdir()
    (root / "class" / "tty" / "tty0").mkdir()
    (root / "devices-proc").write_text(
        "Character devices:\n  1 mem\n180 usb\n\nBlock devices:\n  8 sd\n", encoding="utf-8"
    )
    return sysfs, modules


def _records(root: Path) -> list[str]:
    sysfs, modules = _rich_machine(root)
    return snapshot.records(sysfs, modules, aliases=root / "none", log=lambda: "", procdevices=root / "devices-proc")


def test_devices_without_a_modalias_are_recorded_as_plat(tmp_path: Path) -> None:
    rows = [line.split("\t") for line in _records(tmp_path) if line.startswith("plat\t")]
    assert ["plat", "platform/soc/uart@1000", "of:ns16550a", "", ""] in rows
    assert ["plat", "platform/PNP0C0A:00", "acpi:PNP0C0A", "", ""] in rows
    assert ["plat", "pci0000:00/usb1/1-1", "usbdev:v046DpC52B", "", ""] in rows


def test_usb_interfaces_and_devices_behind_bridges_are_dev_records(tmp_path: Path) -> None:
    devs = {line.split("\t")[1] for line in _records(tmp_path) if line.startswith("dev\t")}
    assert "pci0000:00/0000:00:1c.0" in devs
    assert "pci0000:00/0000:00:1c.0/0000:01:00.0" in devs
    assert "pci0000:00/usb1/1-1/1-1:1.0" in devs


def test_dmi_records_board_identity_but_never_serials(tmp_path: Path) -> None:
    lines = _records(tmp_path)
    assert "dmi\tsys_vendor\tACME" in lines
    assert "dmi\tboard_name\tB1" in lines
    assert not any("SECRET123" in line or "serial" in line for line in lines)


def test_class_and_major_records(tmp_path: Path) -> None:
    lines = _records(tmp_path)
    assert "cls\tnet\tbr0\t\t" in lines, "a virtual interface has a class entry and no device"
    assert "cls\tnet\teth0\tpci0000:00/0000:00:1c.0/0000:01:00.0\t" in lines
    assert not any(line.startswith("cls\ttty") for line in lines)
    assert "chr\tchar\t180\tusb" in lines
    assert "chr\tblock\t8\tsd" in lines


def test_missing_dmi_class_and_proc_devices_are_blind(tmp_path: Path) -> None:
    sysfs, modules, aliases = _unbound_machine(tmp_path)
    lines = snapshot.records(sysfs, modules, aliases=aliases, log=lambda: "")
    kinds = {line.split("\t")[1] for line in lines if line.startswith("blind\t")}
    assert {"dmi", "class", "proc-devices"} <= kinds


def test_every_record_kind_round_trips_through_read_snapshot(tmp_path: Path) -> None:
    lines = _records(tmp_path)
    assert {line.split("\t")[0] for line in lines} >= {"dev", "plat", "mod", "dmi", "cls", "chr", "blind"}
    path = tmp_path / "snap.tsv"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    parsed = read_snapshot(path)
    assert parsed.loaded == ["my_drv", "other"]
    assert len(parsed.devices) == len([line for line in lines if line.startswith("dev\t")])
