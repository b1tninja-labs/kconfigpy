"""``generate`` end to end, on the synthetic kernel tree in ``tests/fixtures``.

No network and no sysfs: ``--snapshot`` reads the fixture snapshot, and ``--current`` gets its records
from a monkeypatched collector. The fixture tree is kernel-shaped but made up, so the expected options
are fixed here by hand rather than by whatever the real kernel would give.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kconfigpy import __main__ as cli
from kconfigpy.kbuild import module_map
from kconfigpy.kconfig import read_kconfig

FIXTURES = Path(__file__).parent / "fixtures"
TREE = FIXTURES / "kernel-tree"
SNAPSHOT = FIXTURES / "snapshot.tsv"

# What the fixture snapshot needs: two bound devices, ACME_NET with its two dependencies, and
# ACME_SERIAL, whose driver name differs from its object name and so goes through the source scan.
EXPECTED_OPTIONS = {"ACME_NET", "ACME_SERIAL", "NETDEVICES", "PCI"}


def _enabled_lines(fragment: str) -> list[str]:
    return [line for line in fragment.splitlines() if line.startswith("CONFIG_")]


def _assert_every_option_has_a_reason(fragment: str) -> None:
    lines = fragment.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("CONFIG_"):
            previous = lines[index - 1]
            assert previous.startswith("# ") and len(previous) > 2, f"{line} has no reason above it"


def test_fixture_tree_has_the_shape_generate_needs() -> None:
    db = read_kconfig(TREE)
    assert db.missing_sources == []
    assert {"PCI", "HAS_IOMEM", "NETDEVICES", "ACME_NET", "ACME_SERIAL"} <= set(db.definitions)
    assert module_map(TREE) == {
        "acme_net": {"ACME_NET"},
        "acme_serial": {"ACME_SERIAL"},
    }


def test_generate_from_snapshot_writes_fragment_and_report(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "out"
    assert cli.main(["generate", "--snapshot", str(SNAPSHOT), "--tree", str(TREE), "--out", str(out)]) == 0

    fragment = (out / "hardware.config").read_text(encoding="utf-8")
    assert set(_enabled_lines(fragment)) == {f"CONFIG_{name}=y" for name in EXPECTED_OPTIONS}
    _assert_every_option_has_a_reason(fragment)
    assert "# device pci:v00001234d00005678 uses driver acme_net\nCONFIG_ACME_NET=y" in fragment
    assert "# device platform:acme-uart uses driver acme_serial_drv\nCONFIG_ACME_SERIAL=y" in fragment

    report = (out / "report.md").read_text(encoding="utf-8")
    assert "## Bound devices (2)" in report
    assert "- `platform:acme-uart`: acme_serial_drv -> ACME_SERIAL" in report
    assert "## Options enabled (4)" in report
    assert "- `HAS_IOMEM`: dependency of ACME_NET" in report

    assert "devices: 2 (2 bound), options enabled: 4, conflicts: 0" in capsys.readouterr().out


def test_generate_current_collects_then_generates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[tuple[str | None, str]] = []
    records = SNAPSHOT.read_text(encoding="utf-8")

    def fake_collect(ssh: str | None = None, ssh_cmd: str = "ssh") -> str:
        calls.append((ssh, ssh_cmd))
        return records

    monkeypatch.setattr(cli, "collect", fake_collect)
    out = tmp_path / "current"
    assert cli.main(["generate", "--current", "--tree", str(TREE), "--out", str(out)]) == 0

    assert calls == [(None, "ssh")]
    assert (out / "snapshot.tsv").read_text(encoding="utf-8") == records
    fresh = (out / "hardware.config").read_text(encoding="utf-8")
    saved = tmp_path / "saved"
    assert cli.main(["generate", "--snapshot", str(SNAPSHOT), "--tree", str(TREE), "--out", str(saved)]) == 0
    assert fresh == (saved / "hardware.config").read_text(encoding="utf-8")
    assert "options enabled: 4" in capsys.readouterr().out


def test_generate_current_passes_the_ssh_host_to_the_collector(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str | None, str]] = []

    def fake_collect(ssh: str | None = None, ssh_cmd: str = "ssh") -> str:
        calls.append((ssh, ssh_cmd))
        return SNAPSHOT.read_text(encoding="utf-8")

    monkeypatch.setattr(cli, "collect", fake_collect)
    args = [
        "generate",
        "--current",
        "--tree",
        str(TREE),
        "--out",
        str(tmp_path),
        "--ssh",
        "router",
        "--ssh-cmd",
        "plink",
    ]
    assert cli.main(args) == 0
    assert calls == [("router", "plink")]


def test_generate_refuses_a_snapshot_with_no_devices(tmp_path: Path) -> None:
    empty = tmp_path / "empty.tsv"
    empty.write_text("mod\tacme_net\n", encoding="utf-8")
    out = tmp_path / "out"
    with pytest.raises(RuntimeError, match="has no device records"):
        cli.main(["generate", "--snapshot", str(empty), "--tree", str(TREE), "--out", str(out)])
    assert not (out / "hardware.config").exists()
    assert not (out / "report.md").exists()


def test_generate_current_refuses_an_empty_collection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "collect", lambda ssh=None, ssh_cmd="ssh": "mod\tacme_net\n")
    out = tmp_path / "out"
    with pytest.raises(RuntimeError, match="has no device records"):
        cli.main(["generate", "--current", "--tree", str(TREE), "--out", str(out)])
    assert not (out / "hardware.config").exists()
