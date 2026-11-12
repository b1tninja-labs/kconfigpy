"""Collect a hardware snapshot from a Linux machine: devices from sysfs and the loaded modules.

Standard library only, and read-only: it reads ``/sys`` and ``/proc/modules`` and writes nothing. That is
why it can also be piped to a remote machine (``ssh host python3 - < snapshot.py``) without installing
the package there. Output is tab-separated, one record per line::

    dev  <sysfs path under /sys/devices>  <modalias>  <driver>  <module>
    mod  <loaded module name>
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

SYSFS = Path("/sys/devices")
MODULES = Path("/proc/modules")


def records(sysfs: Path = SYSFS, modules: Path = MODULES) -> list[str]:
    """Return the snapshot records for one machine."""
    out: list[str] = []
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
        if link.exists():
            driver = link.resolve().name
            if (link / "module").exists():
                module = (link / "module").resolve().name
        out.append("\t".join(["dev", str(device.relative_to(sysfs)), alias, driver, module]))
    try:
        loaded = sorted({line.split()[0] for line in modules.read_text(encoding="utf-8").splitlines() if line.strip()})
    except OSError:
        loaded = []
    out.extend(f"mod\t{name}" for name in loaded)
    return out


def main() -> int:
    for line in records():
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
