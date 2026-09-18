"""
Regression tests for blocking vs advisory severity (WBS 4.2).

test_real_projecttrack_skeleton_rows_are_excluded_not_blended reads ProjectTrack
directly from the real workbook (same approach as the other real-file tests) and
proves the literal done-when against the file's own cited example: rows 14-18
are "design wins worth zero" that must not silently enter a regional total.
"""

from pathlib import Path

import pytest

from app.calc.engine import compute_project_financials
from app.calc.severity import BLOCKING, classify_severity, rollup_with_severity

WORKBOOK = Path(__file__).resolve().parents[3] / "data" / "TrackF (1).xlsx"

COMPLETE_ROW = {
    "project": "Hercules", "region": "Korea", "customer": "SLM",
    "design_status": "Design Win", "stage": "PVT", "part_number": "AX01",
    "eau_kpcs": 1100.0, "disty_asp": 3.0, "confidence": 1.0,
}

SKELETON_ROW = {
    "project": None, "region": "North America", "customer": None,
    "design_status": "Evaluation", "stage": None, "part_number": None,
    "eau_kpcs": 100.0, "disty_asp": None, "confidence": None,
}


def test_classify_severity_flags_missing_asp_or_customer():
    assert classify_severity(COMPLETE_ROW) is None
    assert classify_severity(SKELETON_ROW) == BLOCKING
    assert classify_severity({**COMPLETE_ROW, "customer": None}) == BLOCKING
    assert classify_severity({**COMPLETE_ROW, "disty_asp": None}) == BLOCKING


def test_blocking_row_would_crash_compute_project_financials():
    """The reason blocking exclusion happens before compute, not after: a
    skeleton row is missing exactly what the calc engine needs."""
    with pytest.raises(TypeError):
        compute_project_financials(SKELETON_ROW)


def test_rollup_with_severity_excludes_blocking_without_blending():
    rows = [
        (COMPLETE_ROW, classify_severity(COMPLETE_ROW)),
        (SKELETON_ROW, classify_severity(SKELETON_ROW)),
    ]
    result = rollup_with_severity(rows)

    assert result["included_count"] == 1
    assert result["excluded_count"] == 1
    # The complete row alone: 1100 * 3 = 3300, * confidence 1.0 = 3300.
    assert result["included_total_sales_revenue_k"] == pytest.approx(3300.0)
    assert result["included_total_adjusted_revenue_k"] == pytest.approx(3300.0)


def test_advisory_row_is_counted_but_still_included():
    rows = [(COMPLETE_ROW, "advisory")]
    result = rollup_with_severity(rows)
    assert result["included_count"] == 1
    assert result["advisory_count"] == 1
    assert result["included_total_sales_revenue_k"] == pytest.approx(3300.0)


@pytest.mark.skipif(not WORKBOOK.exists(), reason="TrackF (1).xlsx not present in this checkout")
def test_real_projecttrack_skeleton_rows_are_excluded_not_blended():
    import openpyxl

    wb = openpyxl.load_workbook(WORKBOOK, data_only=True)
    ws = wb["ProjectTrack"]

    rows = []
    for r in range(5, 19):  # rows 5-13 complete, 14-18 skeletons, per the field map doc
        region, customer, end_customer, project, application, product_line, part_number, \
            design_status, stage, mp, eau, unit_set, disty_asp, resale_asp, sales_rev, \
            competitor_part, confidence = (ws.cell(row=r, column=c).value for c in range(1, 18))
        rows.append({
            "project": project, "region": region, "customer": customer,
            "design_status": design_status, "stage": stage, "part_number": part_number,
            "eau_kpcs": eau, "disty_asp": disty_asp, "confidence": confidence,
        })

    assert len(rows) == 14  # 9 complete + 5 skeleton

    classified = [(row, classify_severity(row)) for row in rows]
    assert sum(1 for _, sev in classified if sev == BLOCKING) == 5  # rows 14-18
    assert sum(1 for _, sev in classified if sev is None) == 9  # rows 5-13

    result = rollup_with_severity(classified)

    assert result["included_count"] == 9
    assert result["excluded_count"] == 5

    # Hand-summed from the real O and R columns (Sales Revenue, Adjusted Revenue)
    # for rows 5-13 -- the same nine numbers test_calc_engine.py's EXPECTED table
    # already validates row by row.
    assert result["included_total_sales_revenue_k"] == pytest.approx(82350.0)
    assert result["included_total_adjusted_revenue_k"] == pytest.approx(30915.0)
