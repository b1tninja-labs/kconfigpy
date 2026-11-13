"""Aliases come from the built tree's depmod output, and never from the sources.

The obligation (fwd.modalias): read ``modules.alias`` and ``modules.builtin.alias`` from a built tree,
and refuse when they are missing. The tests below would fail if the reader started deriving aliases from
``MODULE_DEVICE_TABLE`` in source, or if a missing file produced an empty table instead of an error.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kconfigpy.kbuild import BuildArtifactsMissing, module_aliases

SOURCE_ONLY = """\
#include <linux/module.h>
static const struct pci_device_id ids[] = {
\t{ PCI_DEVICE(0x8086, 0x1234) },
\t{ }
};
MODULE_DEVICE_TABLE(pci, ids);
"""


@pytest.fixture
def source_tree(tmp_path: Path) -> Path:
    """A source tree whose driver would alias ``pci:v00008086d00001234`` if aliases were derived from source."""
    (tmp_path / "drivers" / "net").mkdir(parents=True)
    (tmp_path / "drivers" / "net" / "my_drv.c").write_text(SOURCE_ONLY, encoding="utf-8")
    (tmp_path / "drivers" / "net" / "Makefile").write_text("obj-$(CONFIG_DRV) += my-drv.o\n", encoding="utf-8")
    return tmp_path


def test_reads_both_built_alias_files(tmp_path: Path) -> None:
    (tmp_path / "modules.alias").write_text(
        "alias pci:v00008086d00001234* my-drv\nalias usb:v1d6bp0001* hid_generic\n", encoding="utf-8"
    )
    (tmp_path / "modules.builtin.alias").write_text("alias pci:v00001AF4d* virtio_pci\n", encoding="utf-8")
    assert module_aliases(tmp_path) == [
        ("pci:v00008086d00001234*", "my_drv"),
        ("usb:v1d6bp0001*", "hid_generic"),
        ("pci:v00001AF4d*", "virtio_pci"),
    ]


def test_refuses_when_both_files_are_missing(source_tree: Path) -> None:
    with pytest.raises(BuildArtifactsMissing, match=r"modules\.alias or modules\.builtin\.alias"):
        module_aliases(source_tree)


def test_refuses_when_only_the_builtin_file_is_missing(tmp_path: Path) -> None:
    (tmp_path / "modules.alias").write_text("alias pci:v* my_drv\n", encoding="utf-8")
    with pytest.raises(BuildArtifactsMissing, match=r"modules\.builtin\.alias"):
        module_aliases(tmp_path)


def test_source_is_never_read_for_aliases(source_tree: Path) -> None:
    """With the depmod files present but empty, the source's device table must not appear in the result.

    A reader that derived aliases from ``MODULE_DEVICE_TABLE`` would return the PCI id here.
    """
    (source_tree / "modules.alias").write_text("", encoding="utf-8")
    (source_tree / "modules.builtin.alias").write_text("", encoding="utf-8")
    assert module_aliases(source_tree) == []


def test_source_alone_does_not_produce_an_answer(source_tree: Path) -> None:
    """A tree that has the sources and the Makefile but no built aliases is refused, not answered from source."""
    with pytest.raises(BuildArtifactsMissing):
        module_aliases(source_tree)
