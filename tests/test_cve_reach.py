from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from cve_reach import affects, parse_version

V = (6, 18, 62)


def test_fix_on_own_branch_at_or_before_version_clears_it() -> None:
    assert not affects([((4, 14), (6, 18, 22)), ((4, 14), (7, 0))], V)
    assert affects([((4, 14), (6, 18, 22)), ((4, 14), (7, 0))], (6, 18, 20))


def test_dead_branch_zero_marker_is_not_a_finding() -> None:
    assert not affects([((5, 14, 15), (0,)), ((5, 15), (5, 15, 5)), ((5, 15), (5, 16))], V)


def test_unfixed_start_after_the_last_branch_fix_reopens_the_bug() -> None:
    pairs = [((6, 18, 32), (6, 18, 33)), ((6, 19), (7, 1)), ((6, 18, 57), (0,))]
    assert affects(pairs, V)
    assert not affects(pairs, (6, 18, 40))


def test_zero_marker_counts_on_own_branch_or_from_mainline() -> None:
    assert affects([((6, 18, 40), (0,))], V)
    assert affects([((5, 10), (0,))], V)


def test_later_mainline_fix_without_backport_is_a_finding() -> None:
    assert affects([((2, 6, 24), (7, 2, 10)), ((2, 6, 24), (7, 3))], V)


def test_bug_introduced_after_this_version_does_not_apply() -> None:
    assert not affects([((6, 19), (7, 1))], V)


def test_release_candidates_parse() -> None:
    assert parse_version("4.4-rc1") == (4, 4)
