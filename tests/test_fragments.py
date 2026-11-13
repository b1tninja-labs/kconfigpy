"""Fragments from configurations: a diff of two configs, and a minimal defconfig."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from kconfigpy.fragments import FragmentLine, diff_fragment, minimal_defconfig, render
from kconfigpy.kconfig import read_kconfig
from kconfigpy.verify import read_config

GOLDEN = """\
CONFIG_A=y
CONFIG_B=m
CONFIG_ONLY_GOLDEN=y
CONFIG_SAME=y
# CONFIG_OFF is not set
"""
BUILD = """\
CONFIG_A=y
CONFIG_B=y
CONFIG_ONLY_BUILD=256
CONFIG_SAME=y
# CONFIG_OFF is not set
"""


def configs(tmp_path: Path) -> tuple[dict[str, str], dict[str, str]]:
    (tmp_path / "golden").write_text(GOLDEN, encoding="utf-8")
    (tmp_path / "build").write_text(BUILD, encoding="utf-8")
    return read_config(tmp_path / "golden"), read_config(tmp_path / "build")


def test_diff_lists_each_differing_option_with_its_reason(tmp_path: Path) -> None:
    golden, build = configs(tmp_path)
    assert diff_fragment(golden, build) == [
        FragmentLine("B", "y", "changed from m to y"),
        FragmentLine("ONLY_BUILD", "256", "only in build"),
        FragmentLine("ONLY_GOLDEN", None, "only in golden"),
    ]
    assert render(diff_fragment(golden, build)) == (
        "# changed from m to y\nCONFIG_B=y\n"
        "# only in build\nCONFIG_ONLY_BUILD=256\n"
        "# only in golden\n# CONFIG_ONLY_GOLDEN is not set\n"
    )


def test_diff_of_equal_configs_is_empty() -> None:
    assert diff_fragment({"A": "y"}, {"A": "y"}) == []


def test_diff_applied_to_golden_gives_build(tmp_path: Path) -> None:
    golden, build = configs(tmp_path)
    result = dict(golden)
    for line in diff_fragment(golden, build):
        if line.value is None:
            result.pop(line.symbol)
        else:
            result[line.symbol] = line.value
    assert result == build


def test_minimal_keeps_only_what_differs_from_the_baseline() -> None:
    full = {"A": "y", "B": "y", "C": "m", "D": "y"}
    baseline = {"A": "y", "B": "n_default", "D": "y", "E": "y"}
    lines = minimal_defconfig(full, baseline)
    assert [line.text for line in lines] == [
        "CONFIG_B=y",
        "CONFIG_C=m",
        "# CONFIG_E is not set",
    ]
    assert lines[0].reason == "differs from the kernel's own default n_default"
    assert lines[1].reason == "set here, off by the kernel's own default"
    assert lines[2].reason == "off here, the kernel's own default is y"


def test_minimal_plus_baseline_reproduces_the_full_config() -> None:
    full = {"A": "y", "B": "m", "NUM": "4"}
    baseline = {"A": "y", "B": "y", "GONE": "y", "NUM": "1"}
    rebuilt = dict(baseline)
    for line in minimal_defconfig(full, baseline):
        if line.value is None:
            rebuilt.pop(line.symbol)
        else:
            rebuilt[line.symbol] = line.value
    assert rebuilt == full


def test_minimal_of_a_config_equal_to_its_baseline_is_empty() -> None:
    assert minimal_defconfig({"A": "y"}, {"A": "y"}) == []


def test_minimal_drops_an_option_the_kernel_derives_but_keeps_an_unknown_one(tmp_path: Path) -> None:
    (tmp_path / "Kconfig").write_text(
        'config USER_OPT\n\tbool "user"\n\nconfig DERIVED\n\tbool\n\tdefault y\n', encoding="utf-8"
    )
    db = read_kconfig(tmp_path)
    full = {"USER_OPT": "y", "DERIVED": "y", "NOT_IN_TREE": "y"}
    assert [line.symbol for line in minimal_defconfig(full, {}, db)] == ["NOT_IN_TREE", "USER_OPT"]
    assert [line.symbol for line in minimal_defconfig(full, {})] == ["DERIVED", "NOT_IN_TREE", "USER_OPT"]


KERNEL_CONFIG = Path(r"D:\code\aws\router\firmware\out\kernel.config")
TREE = "/work/src/linux-6.18.62"


def docker_ready() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=10).returncode == 0
    except subprocess.TimeoutExpired:
        return False


@pytest.mark.skipif(not (KERNEL_CONFIG.exists() and docker_ready()), reason="needs Docker and the router kernel.config")
def test_minimal_defconfig_expands_to_the_same_config_under_the_kernels_conf(tmp_path: Path) -> None:
    """Evidence for `fwd.minimal`: the kernel's own conf expands the minimal fragment back to the input."""
    full = read_config(KERNEL_CONFIG)

    def conf(allconfig: str | None, out: str) -> dict[str, str]:
        env = f"KCONFIG_ALLCONFIG=/io/{allconfig} " if allconfig else ""
        script = f"mkdir -p /tmp/o && {env}make -C {TREE} O=/tmp/o ARCH=x86_64 alldefconfig >/dev/null && cp /tmp/o/.config /io/{out}"
        subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "-v",
                "rooter-build:/work:ro",
                "-v",
                f"{tmp_path}:/io",
                "rooter-builder:latest",
                "sh",
                "-c",
                script,
            ],
            check=True,
            timeout=900,
        )
        return read_config(tmp_path / out)

    baseline = conf(None, "baseline.config")
    (tmp_path / "frag").write_text(render(minimal_defconfig(full, baseline)), encoding="utf-8")
    assert conf("frag", "expanded.config") == full
