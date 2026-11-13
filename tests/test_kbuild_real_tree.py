"""Excerpts from the real router kernel build (6.18.62, CONFIG_MODULES off), read from the rooter-build volume.

The built tree has no ``modules.alias`` and no ``modules.builtin.alias``: depmod never ran, because the
kernel was built with ``# CONFIG_MODULES is not set``. The reader must refuse that tree, naming both files.
The excerpts below are copied verbatim from ``/work/o-6.18.62``; see docs/modalias.md for the counts.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kconfigpy.kbuild import BuildArtifactsMissing, module_aliases, modules_enabled

# Real first lines of /work/o-6.18.62/modules.builtin (one path per line, 89 lines in the whole file).
REAL_MODULES_BUILTIN = (
    "kernel/fs/binfmt_script.ko\nkernel/fs/mbcache.ko\nkernel/fs/ext4/ext4.ko\nkernel/fs/jbd2/jbd2.ko\n"
)

# Real records from /work/o-6.18.62/modules.builtin.modinfo. The file has no newlines: each record is
# NUL-terminated, and these are the records for ext4, one PCI alias, one ACPI alias and one block alias.
REAL_MODINFO_RECORDS = [
    "ext4.file=fs/ext4/ext4",
    "ext4.alias=fs-ext4",
    "ext4.alias=ext3",
    "ext4.alias=fs-ext3",
    "ehci_pci.alias=pci:v0000104Ad0000CC00sv*sd*bc*sc*i*",
    "rtc_cmos.alias=acpi*:PNP0B02:*",
    "sd_mod.alias=block-major-135-*",
]

# Real lines from /work/o-6.18.62/.config.
REAL_CONFIG_EXCERPT = "CONFIG_MODULES_USE_ELF_RELA=y\n# CONFIG_MODULES is not set\n"


@pytest.fixture
def router_tree(tmp_path: Path) -> Path:
    """The real excerpts laid out as the built tree lays them out."""
    (tmp_path / "modules.builtin").write_text(REAL_MODULES_BUILTIN, encoding="utf-8")
    (tmp_path / "modules.builtin.modinfo").write_bytes(
        b"".join(record.encode("utf-8") + b"\0" for record in REAL_MODINFO_RECORDS)
    )
    (tmp_path / ".config").write_text(REAL_CONFIG_EXCERPT, encoding="utf-8")
    return tmp_path


def test_router_built_tree_refuses_module_aliases(router_tree: Path) -> None:
    """The real tree has no depmod output, so the reader refuses it and names both missing files."""
    with pytest.raises(BuildArtifactsMissing, match=r"modules\.alias or modules\.builtin\.alias"):
        module_aliases(router_tree)


def test_router_config_says_modules_are_off(router_tree: Path) -> None:
    assert modules_enabled(router_tree / ".config") is False


def test_modinfo_alias_records_are_not_modules_alias_lines(router_tree: Path) -> None:
    """The alias data that exists in the tree is ``module.alias=pattern`` records, not ``alias pattern module``.

    Writing them into a modules.alias file must not produce answers: the reader takes only the depmod
    three-field form, so these records give nothing.
    """
    (router_tree / "modules.alias").write_text("\n".join(REAL_MODINFO_RECORDS) + "\n", encoding="utf-8")
    (router_tree / "modules.builtin.alias").write_text("", encoding="utf-8")
    assert module_aliases(router_tree) == []
