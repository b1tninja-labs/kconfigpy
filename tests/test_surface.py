from __future__ import annotations

from pathlib import Path

import pytest

from kconfigpy.kbuild import module_map
from kconfigpy.surface import read_banned, report_text, surface
from kconfigpy.verify import read_config


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_banned_list_is_read_one_option_per_line(tmp_path: Path) -> None:
    listing = write(
        tmp_path / "banned.list",
        "# The build fails if any of these end up enabled.\n"
        "MODULES\n"
        "\n"
        "# Runtime kernel changes\n"
        "KEXEC  # trailing comment\n"
        "CONFIG_DEVMEM\n"
        "KEXEC\n",
    )
    assert read_banned(listing) == ["MODULES", "KEXEC", "DEVMEM"]


def test_banned_list_refuses_a_line_that_is_not_one_name(tmp_path: Path) -> None:
    listing = write(tmp_path / "banned.list", "KEXEC\nUSER_NS IO_URING\n")
    with pytest.raises(ValueError, match=r"banned\.list:2: 'USER_NS IO_URING' is not one option name"):
        read_banned(listing)


def test_enabled_banned_option_is_reported_from_a_fragment(tmp_path: Path) -> None:
    banned = read_banned(write(tmp_path / "banned.list", "KEXEC\nSCTP\nMODULES\n"))
    fragment = write(tmp_path / "hardware.config", "CONFIG_KEXEC=y\nCONFIG_SCTP=m\nCONFIG_PCI=y\n")
    result = surface(read_config(fragment), {}, banned)
    assert result.banned == {"KEXEC": "y", "SCTP": "m"}


def test_option_that_is_off_is_not_reported_as_banned(tmp_path: Path) -> None:
    banned = read_banned(write(tmp_path / "banned.list", "MODULES\nKEXEC\n"))
    fragment = write(tmp_path / "config", "CONFIG_MODULES=n\n# CONFIG_KEXEC is not set\n")
    result = surface(read_config(fragment), {}, banned)
    assert result.banned == {}
    assert "MODULES" not in result.enabled


def test_the_banned_file_is_the_only_list_checked(tmp_path: Path) -> None:
    banned = read_banned(write(tmp_path / "banned.list", "ZZZ_TEST_ONLY\n"))
    result = surface({"KEXEC": "y", "ZZZ_TEST_ONLY": "y"}, {}, banned)
    assert result.banned == {"ZZZ_TEST_ONLY": "y"}


def test_each_enabled_option_brings_the_modules_it_builds(tmp_path: Path) -> None:
    net = tmp_path / "drivers" / "net"
    net.mkdir(parents=True)
    write(net / "Makefile", "obj-$(CONFIG_DRV) += my-drv.o\nobj-$(CONFIG_SCTP) += sctp.o\n")
    modules = module_map(tmp_path)
    result = surface({"DRV": "y", "SCTP": "m", "KEXEC": "y"}, modules, ["SCTP", "KEXEC"])
    assert result.code == {"DRV": ["my_drv"], "SCTP": ["sctp"]}
    assert result.unmapped == ["KEXEC"]
    assert result.banned == {"SCTP": "m", "KEXEC": "y"}


def test_unmapped_option_is_unknown_not_guessed() -> None:
    result = surface({"KEXEC": "y"}, {"my_drv": {"DRV"}}, [])
    assert result.code == {}
    assert result.unmapped == ["KEXEC"]


def test_report_names_banned_options_and_unknown_mappings() -> None:
    result = surface({"KEXEC": "y", "DRV": "y"}, {"my_drv": {"DRV"}}, ["KEXEC"])
    text = report_text(result)
    assert "## Banned options enabled\n- `KEXEC=y`\n" in text
    assert "- `DRV`: my_drv\n" in text
    assert "## Enabled options with no module mapping (unknown, not guessed)\n- `KEXEC`\n" in text
