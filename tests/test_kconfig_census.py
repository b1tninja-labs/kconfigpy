"""The census counts statements without trusting the reader, so its numbers can check the reader's."""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from kconfig_census import classify, scan

from kconfigpy.kconfig import parse_expr


def test_scan_counts_statements_and_skips_help_bodies(tmp_path: Path) -> None:
    text = 'config A\n\tbool "a"\n\tselect B if C\n\thelp\n\t  select NOT_COUNTED\n\t  config NEITHER\n\nconfig B\n\tbool\n'
    path = tmp_path / "Kconfig"
    path.write_text(text, encoding="utf-8")
    counts: Counter[str] = Counter()
    scan(path, counts)
    assert (counts["config"], counts["select"], counts["select ... if"], counts["help"]) == (2, 1, 1, 1)


def test_classify_separates_the_three_kinds_of_unevaluated_term() -> None:
    counts: Counter[str] = Counter()
    classify(parse_expr("A && $(cc-option,-x) && N >= 4 && S = T"), counts)
    assert counts["unknown: macro call"] == 1
    assert counts["unknown: ordered comparison"] == 1
    assert counts["unknown: equality that is not against y/m/n"] == 1
    assert counts["expression terms"] == 7
