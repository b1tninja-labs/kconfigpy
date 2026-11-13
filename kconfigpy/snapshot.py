"""Collect a hardware snapshot from a Linux machine: devices from sysfs, loaded modules, and what it missed.

Standard library only, and read-only: it reads ``/sys``, ``/proc/modules``, the module alias table and
the kernel log, and writes nothing. That is why it can also be piped to a remote machine
(``ssh host python3 - < snapshot.py``) without installing the package there. Output is tab-separated,
one record per line::

    dev    <sysfs path under /sys/devices>  <modalias>  <driver>  <module>
    mod    <loaded module name>
    seen   <module name>  <source>  <detail>
    blind  <what>  <why it could not be seen>
    plat   <sysfs path>  <identity,...>  <driver>  <module>
    dmi    <field>  <value>
    cls    <class>  <name>  <sysfs path of its device>  <driver>
    chr    <char|block>  <major>  <name>

``dev`` and ``mod`` are the state of the machine now. A snapshot of that alone misses modules that load
only at boot or on demand (``localmodconfig`` has the same blind spot), so two more record kinds say what
else was found and what could not be. A reader that does not know ``seen`` or ``blind`` ignores them.

``seen`` names a module that is **not** in ``/proc/modules`` but that the machine shows evidence of, from
sources every stock Linux box has:

- ``sysmodule``: ``/sys/module/<name>/initstate`` reads ``coming`` or ``going``, a module mid-load or
  mid-unload. A settled module has ``live`` and is already in ``/proc/modules``; a built-in has no
  ``initstate`` and needs no module, so neither is reported.
- ``dmesg``: the kernel log names the module in a message only a loaded module can produce (taint,
  signature, symbol and version-mismatch notices). Those are logged when the module loads, so they survive
  its unloading. Read with ``dmesg``, which ``kernel.dmesg_restrict`` may forbid to non-root.
- ``alias``: a device with no bound driver whose ``modalias`` matches a pattern in
  ``/lib/modules/$(uname -r)/modules.alias``. The module is not loaded, and loading it on demand
  (``modprobe`` from udev) is what would claim the device. The detail is the device path.

Four more kinds cover what a bare ``modalias`` walk does not reach, all from sysfs and procfs:

- ``plat``: a device directory with **no** ``modalias`` file but an identity in its ``uevent``
  (``OF_COMPATIBLE_n``, ``PNP_ID``), its ``firmware_node/hid`` (the ACPI id) or its USB descriptor
  (``idVendor``/``idProduct``). Identities are ``of:``, ``pnp:``, ``acpi:`` or ``usbdev:`` prefixed.
  USB *interface* descriptors need nothing extra: an interface has a ``usb:...ic..isc..ip..`` modalias and
  is a ``dev`` record already. Devices behind PCI bridges likewise: the walk descends through bridges, and
  the bridge is a ``dev`` of its own, so bridge options have evidence too.
- ``dmi``: board identity from ``/sys/class/dmi/id`` (vendor, product, board, BIOS, chassis). Serial
  numbers and the system UUID are deliberately not read: they identify one machine, not a kind of one.
- ``cls``: each ``/sys/class/<class>/<name>`` with the device behind it and that device's driver. It adds
  what has no hardware modalias, such as virtual network interfaces (``br0``, ``wg0``), and names the class
  (net, block, input, drm, sound) a driver serves. ``tty`` and ``vc`` are skipped as noise.
- ``chr``: the character and block major numbers from ``/proc/devices``, the in-kernel subsystems that
  registered even when no sysfs device shows it.

``blind`` lists what the snapshot could not see on this run, such as a kernel log it was not allowed to
read, plus the limits that always apply. A fragment built from the snapshot should say it did not cover
them. The snapshot refuses off Linux and refuses an empty sysfs rather than write a hollow file.
"""

from __future__ import annotations

import fnmatch
import os
import platform
import re
import subprocess
import sys
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

SYSFS = Path("/sys/devices")
MODULES = Path("/proc/modules")

# Messages the kernel prints only for a module that was being loaded, always prefixed with its name.
_LOG_MODULE = re.compile(
    r"^(?:\[[^\]]*\]\s*)?([A-Za-z0-9_-]+): "
    r"(?:loading out-of-tree module|module verification failed|module license|Unknown symbol|"
    r"exports duplicate symbol|disagrees about version|module_layout)"
)

# What no source here can recover, however readable the machine is.
_ALWAYS_BLIND = (
    (
        "unlogged-unload",
        "a module loaded and unloaded earlier leaves no trace unless it logged one of the messages above",
    ),
    ("absent-hardware", "a device never attached since boot (USB, hot-plug, a card not fitted) has no record"),
    ("log-rotated", "the kernel log ring buffer is bounded, so an early module on a long-running machine may be gone"),
)


def _normalize(name: str) -> str:
    return name.replace("-", "_")


def _binding(device: Path) -> tuple[str, str]:
    """The driver bound to a device directory and the module it lives in; either may be empty."""
    link = device / "driver"
    if not link.exists():
        return "", ""
    module = (link / "module").resolve().name if (link / "module").exists() else ""
    return link.resolve().name, module


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def _identity(device: Path, files: list[str]) -> list[str]:
    """Identities of a device that has no ``modalias`` file: device tree, PnP, ACPI and USB device ids."""
    ids: list[str] = []
    for line in _read(device / "uevent").splitlines():
        key, _, value = line.partition("=")
        if key.startswith("OF_COMPATIBLE_") and value:
            ids.append(f"of:{value}")
        elif key == "PNP_ID" and value:
            ids.append(f"pnp:{value}")
    hid = _read(device / "firmware_node" / "hid")
    if hid:
        ids.append(f"acpi:{hid}")
    if "idVendor" in files and "idProduct" in files:
        ids.append(f"usbdev:v{_read(device / 'idVendor').upper()}p{_read(device / 'idProduct').upper()}")
    return ids


_DMI_FIELDS = (
    "sys_vendor",
    "product_name",
    "product_version",
    "board_vendor",
    "board_name",
    "board_version",
    "bios_vendor",
    "bios_version",
    "chassis_type",
)
_SKIPPED_CLASSES = {"tty", "vc"}


def _dmi_records(dmi: Path) -> list[str] | None:
    if not dmi.is_dir():
        return None
    return [f"dmi\t{field}\t{_read(dmi / field)}" for field in _DMI_FIELDS if _read(dmi / field)]


def _class_records(sysclass: Path, sysfs: Path) -> list[str] | None:
    if not sysclass.is_dir():
        return None
    out = []
    root = sysfs.resolve()
    for cls in sorted(sysclass.iterdir()):
        if cls.name in _SKIPPED_CLASSES or not cls.is_dir():
            continue
        for entry in sorted(cls.iterdir()):
            device = entry / "device"
            where = driver = ""
            if device.exists():
                real = device.resolve()
                where = str(real.relative_to(root)) if real.is_relative_to(root) else real.name
                driver = _binding(real)[0]
            out.append(f"cls\t{cls.name}\t{entry.name}\t{where}\t{driver}")
    return out


def _char_records(path: Path) -> list[str] | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    out, kind = [], ""
    for line in text.splitlines():
        if line.startswith("Character devices"):
            kind = "char"
        elif line.startswith("Block devices"):
            kind = "block"
        elif kind and len(line.split()) == 2 and line.split()[0].isdigit():
            major, name = line.split()
            out.append(f"chr\t{kind}\t{major}\t{name}")
    return out


def kernel_log() -> str | None:
    """The kernel log as ``dmesg`` prints it, or ``None`` when it cannot be read."""
    try:
        done = subprocess.run(["dmesg"], capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def default_aliases() -> Path:
    return Path("/lib/modules") / platform.release() / "modules.alias"


def _alias_index(path: Path) -> dict[str, list[tuple[str, str]]]:
    """``modules.alias`` as ``{bus prefix: [(pattern, module)]}``, so a device is tried only against its bus."""
    index: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] == "alias":
            index[parts[1].split(":", 1)[0]].append((parts[1], _normalize(parts[2])))
    return index


def _seen_from_sysmodule(sysmodule: Path, loaded: set[str]) -> list[tuple[str, str, str]]:
    found = []
    for entry in sorted(sysmodule.iterdir()):
        try:
            state = (entry / "initstate").read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if state in ("coming", "going") and _normalize(entry.name) not in loaded:
            found.append((_normalize(entry.name), "sysmodule", state))
    return found


def _seen_from_log(text: str, loaded: set[str]) -> list[tuple[str, str, str]]:
    names: dict[str, str] = {}
    for line in text.splitlines():
        match = _LOG_MODULE.match(line.strip())
        if match and _normalize(match.group(1)) not in loaded:
            names.setdefault(_normalize(match.group(1)), line.strip().split(": ", 1)[-1][:60])
    return [(name, "dmesg", detail) for name, detail in sorted(names.items())]


def records(
    sysfs: Path = SYSFS,
    modules: Path = MODULES,
    *,
    sysmodule: Path | None = None,
    aliases: Path | None = None,
    dmi: Path | None = None,
    sysclass: Path | None = None,
    procdevices: Path | None = None,
    log: Callable[[], str | None] = kernel_log,
) -> list[str]:
    """Return the snapshot records for one machine.

    ``sysmodule`` defaults to ``/sys/module`` beside ``sysfs`` (as do ``/sys/class`` and its ``dmi/id``,
    and ``/proc/devices`` beside ``modules``), ``aliases`` to the running kernel's
    ``modules.alias``, and ``log`` to ``dmesg``; they are parameters so a test can supply a fake machine.
    """
    if sys.platform != "linux":
        raise NotImplementedError(f"the snapshot reads Linux sysfs; this is {sys.platform}. Use --ssh HOST.")
    if not sysfs.is_dir():
        raise FileNotFoundError(f"{sysfs} is missing: not a Linux sysfs, so there is nothing to snapshot")
    sysmodule = sysmodule if sysmodule is not None else sysfs.parent / "module"
    aliases = aliases if aliases is not None else default_aliases()
    dmi = dmi if dmi is not None else sysfs.parent / "class" / "dmi" / "id"
    sysclass = sysclass if sysclass is not None else sysfs.parent / "class"
    procdevices = procdevices if procdevices is not None else modules.parent / "devices"
    out: list[str] = []
    platform_devices: list[str] = []
    unbound: list[tuple[str, str]] = []
    for dirpath, _dirs, files in os.walk(sysfs):
        device = Path(dirpath)
        relative = str(device.relative_to(sysfs))
        if "modalias" not in files:
            ids = _identity(device, files)
            if ids:
                platform_devices.append("\t".join(["plat", relative, ",".join(ids), *_binding(device)]))
            continue
        try:
            alias = (device / "modalias").read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if not alias:
            continue
        driver, module = _binding(device)
        if not driver:
            unbound.append((relative, alias))
        out.append("\t".join(["dev", relative, alias, driver, module]))
    if not out:
        raise RuntimeError(f"{sysfs} has no device with a modalias: refusing to write an empty snapshot")
    try:
        loaded = sorted({line.split()[0] for line in modules.read_text(encoding="utf-8").splitlines() if line.strip()})
    except OSError:
        loaded = []
    out.extend(platform_devices)
    out.extend(f"mod\t{name}" for name in loaded)
    loaded_set = {_normalize(name) for name in loaded}

    blind: list[tuple[str, str]] = []
    seen: list[tuple[str, str, str]] = []
    try:
        seen += _seen_from_sysmodule(sysmodule, loaded_set)
    except OSError as exc:
        blind.append(("sysmodule", f"cannot read {sysmodule}: {exc.strerror or exc}"))
    text = log()
    if text is None:
        blind.append(("dmesg", "the kernel log could not be read (kernel.dmesg_restrict without root, or no dmesg)"))
    else:
        seen += _seen_from_log(text, loaded_set)
    try:
        index = _alias_index(aliases)
    except OSError as exc:
        blind.append(("modules.alias", f"cannot read {aliases}: {exc.strerror or exc}"))
        if unbound:
            blind.append(
                ("unbound-devices", f"{len(unbound)} devices have no driver and could not be matched to a module")
            )
    else:
        for path, alias in unbound:
            for pattern, name in index.get(alias.split(":", 1)[0], []):
                if name not in loaded_set and fnmatch.fnmatchcase(alias, pattern):
                    seen.append((name, "alias", path))
    out.extend(f"seen\t{name}\t{source}\t{detail}" for name, source, detail in sorted(set(seen)))
    for what, found, absent in (
        ("dmi", _dmi_records(dmi), f"no {dmi}: no firmware DMI tables (not x86/UEFI), so no board identity"),
        ("class", _class_records(sysclass, sysfs), f"cannot read {sysclass}: no class view of devices"),
        ("proc-devices", _char_records(procdevices), f"cannot read {procdevices}: no major-number list"),
    ):
        if found is None:
            blind.append((what, absent))
        else:
            out.extend(found)
    blind.extend(_ALWAYS_BLIND)
    out.extend(f"blind\t{what}\t{why}" for what, why in blind)
    return out


def main() -> int:
    for line in records():
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
