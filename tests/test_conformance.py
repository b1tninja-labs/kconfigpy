"""The comparison behind tools/conformance.py, with no Docker: what is dropped, what is extra, and the rates."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from conformance import Comparison, fragment_text, propose, resolved_on, summarize  # noqa: E402

from kconfigpy.kconfig import read_kconfig  # noqa: E402

KCONFIG = """\
config TOP
\tbool "Top"
\tselect KEPT

config KEPT
\tbool "Kept"

config GUARDED
\tbool "Guarded"
\tdepends on !TOP
"""


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    (tmp_path / "Kconfig").write_text(KCONFIG, encoding="utf-8")
    return tmp_path


def test_proposal_follows_select_and_fragment_lists_each_option_as_y(tree: Path) -> None:
    db = read_kconfig(tree, "x86")
    assert propose(db, "TOP") == {"TOP", "KEPT"}
    assert fragment_text({"TOP", "KEPT"}) == "CONFIG_KEPT=y\nCONFIG_TOP=y\n"


def test_dropped_and_extra_are_the_two_directions_of_disagreement() -> None:
    # kconfigpy proposed A and B; conf kept A and also enabled a default-on C that was never proposed.
    comparison = Comparison("A", proposed={"A", "B"}, resolved={"A", "C"})
    assert comparison.dropped == {"B"}
    assert comparison.extra == {"C"}


def test_full_agreement_has_nothing_dropped_and_no_extra() -> None:
    comparison = Comparison("A", proposed={"A"}, resolved={"A"})
    assert comparison.dropped == set()
    assert comparison.extra == set()


def test_only_y_counts_as_resolved_so_m_and_unset_do_not_agree() -> None:
    config = {"A": "y", "B": "m", "C": "n", "D": "y"}
    assert resolved_on(config) == {"A", "D"}


def test_summary_rates_and_most_common_drop() -> None:
    comparisons = [
        Comparison("r1", proposed={"A", "B"}, resolved={"A", "X"}),  # B dropped
        Comparison("r2", proposed={"B", "C"}, resolved={"B", "C", "X"}),  # nothing dropped
        Comparison("r3", proposed={"B"}, resolved={"A"}),  # B dropped again
    ]
    summary = summarize(comparisons)
    assert summary["requests"] == 3
    assert summary["requests_with_no_drop"] == 1
    assert summary["proposed"] == 5
    assert summary["kept"] == 3
    assert summary["dropped"] == 2
    assert summary["extra"] == 3  # X in r1, X in r2, A in r3
    assert summary["kept_share"] == pytest.approx(0.6)
    most_dropped = summary["most_dropped"]
    assert isinstance(most_dropped, list) and most_dropped[0] == ("B", 2)


def test_summary_with_nothing_proposed_has_no_rate_rather_than_a_division_error() -> None:
    summary = summarize([Comparison("r", proposed=set(), resolved=set())])
    assert summary["kept_share"] is None
    assert summary["proposed_share_of_conf"] is None
