"""Collect a hardware snapshot from a Linux machine: devices from sysfs, loaded modules, and what it missed.

Standard library only, and read-only: it reads ``/sys``, ``/proc/modules``, the module alias table and
the kernel log, and writes nothing. That is why it can also be piped to a remote machine
(``ssh host python3 - < snapshot.py``) without installing the package there. Output is tab-separated,
one record per line::

    dev    <sysfs path under /sys/devices>  <modalias>  <driver>  <module>
    mod    <loaded module name>
    seen   <module name>  <source>  <detail>
    blind  <what>  <why it could not be seen>

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
    log: Callable[[], str | None] = kernel_log,
) -> list[str]:
    """Return the snapshot records for one machine.

    ``sysmodule`` defaults to ``/sys/module`` beside ``sysfs``, ``aliases`` to the running kernel's
    ``modules.alias``, and ``log`` to ``dmesg``; they are parameters so a test can supply a fake machine.
    """
    if sys.platform != "linux":
        raise NotImplementedError(f"the snapshot reads Linux sysfs; this is {sys.platform}. Use --ssh HOST.")
    if not sysfs.is_dir():
        raise FileNotFoundError(f"{sysfs} is missing: not a Linux sysfs, so there is nothing to snapshot")
    sysmodule = sysmodule if sysmodule is not None else sysfs.parent / "module"
    aliases = aliases if aliases is not None else default_aliases()
    out: list[str] = []
    unbound: list[tuple[str, str]] = []
    for dirpath, _dirs, files in os.walk(sysfs):
        if "modalias" not in files:
            continue
        device = Path(dirpath)
        try:
            alias = (device / "modalias").read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if not alias:
            continue
        driver = module = ""
        link = device / "driver"
        relative = str(device.relative_to(sysfs))
        if link.exists():
            driver = link.resolve().name
            if (link / "module").exists():
                module = (link / "module").resolve().name
        else:
            unbound.append((relative, alias))
        out.append("\t".join(["dev", relative, alias, driver, module]))
    if not out:
        raise RuntimeError(f"{sysfs} has no device with a modalias: refusing to write an empty snapshot")
    try:
        loaded = sorted({line.split()[0] for line in modules.read_text(encoding="utf-8").splitlines() if line.strip()})
    except OSError:
        loaded = []
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
    blind.extend(_ALWAYS_BLIND)
    out.extend(f"blind\t{what}\t{why}" for what, why in blind)
    return out


def main() -> int:
    for line in records():
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
