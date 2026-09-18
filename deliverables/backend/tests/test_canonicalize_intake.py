"""
Regression tests for canonicalisation (WBS 3.4).

test_regional_rollup_over_the_real_file_collapses_spelling_variants reads the
actual TrackF (1).xlsx directly -- not a copied-out fixture -- to prove the
literal done-when ("the regional roll-up over the real file produces [fewer]
regions, not [more] spellings of [the same] regions") against real data, not a
synthetic stand-in. The read here is deliberately narrow (Region/Customer/Design
Status columns only, five known tabs, fixed header row): it is not WBS 3.1 (the
Workbook reader), which still has to handle the two-row header, shifted terminal-
tab columns, and every other column. Skipped if the workbook is not present so
the rest of the suite is not coupled to a large binary file.
"""

from pathlib import Path

import pytest

from app.intake.canonicalize import canonicalize_row

WORKBOOK = Path(__file__).resolve().parents[3] / "data" / "TrackF (1).xlsx"


def test_known_variants_canonicalize():
    result = canonicalize_row({"region": "KR", "customer": "MOBIS", "design_status": "M/P", "stage": "pvt"})
    assert result.canonical == {"region": "Korea", "customer": "Mobis", "design_status": "Mass Production", "stage": "PVT"}
    assert result.findings == []


def test_unmapped_region_becomes_a_finding_not_a_new_category():
    result = canonicalize_row({"region": "LATAM", "customer": "SLM"})
    assert "region" not in result.canonical  # never invented at read time
    assert result.canonical["customer"] == "SLM"
    assert len(result.findings) == 1
    assert result.findings[0].field == "region"
    assert result.findings[0].raw_value == "LATAM"


def test_nre_and_tbd_design_status_become_findings():
    for raw in ("NRE", "TBD"):
        result = canonicalize_row({"design_status": raw})
        assert "design_status" not in result.canonical
        assert result.findings[0].raw_value == raw


def test_passthrough_fields_are_untouched():
    result = canonicalize_row({"part_number": "AX01", "eau_kpcs": 1100, "confidence": 0.5})
    assert result.canonical == {"part_number": "AX01", "eau_kpcs": 1100, "confidence": 0.5}
    assert result.findings == []


def test_missing_fields_are_simply_absent_not_findings():
    result = canonicalize_row({"region": "Korea"})
    assert result.canonical == {"region": "Korea"}
    assert result.findings == []


@pytest.mark.skipif(not WORKBOOK.exists(), reason="TrackF (1).xlsx not present in this checkout")
def test_regional_rollup_over_the_real_file_collapses_spelling_variants():
    import openpyxl

    wb = openpyxl.load_workbook(WORKBOOK, data_only=True)
    raw_regions: set[str] = set()
    canonical_regions: set[str] = set()
    unmapped_raw_regions: set[str] = set()

    # Region is column A on every one of these five tabs (Sheet1 is explicitly
    # out of scope -- "the agent does not read this tab at all", per the field map
    # doc). max_row bounds each sweep to the real data rows: FCST_Revenue rows
    # 20-24 are the tab's own broken regional subtotal labels ("Korea Region",
    # "Elevation Micro Total", ...), documented as broken and not opportunity
    # rows at all -- reading past row 14 there would count roll-up labels as if
    # they were region values.
    data_rows = {
        "ProjectTrack": 18, "Funnel": 12, "FCST_Revenue": 14,
        "Mass Production": 5, "Design Lost": 5,
    }
    for sheet_name, max_row in data_rows.items():
        ws = wb[sheet_name]
        for row in ws.iter_rows(min_row=5, max_row=max_row, max_col=1, values_only=True):
            raw = row[0]
            if raw is None:
                continue
            raw_regions.add(raw)
            result = canonicalize_row({"region": raw})
            if "region" in result.canonical:
                canonical_regions.add(result.canonical["region"])
            else:
                unmapped_raw_regions.add(raw)

    # The real file: "Korea" and "KR" are two spellings of one region.
    assert {"Korea", "KR"}.issubset(raw_regions)
    assert len(canonical_regions) < len(raw_regions)

    # Canonicalizing collapses every resolvable spelling onto David's list.
    # "North America" -> "US" is the provisional mapping in the decision register.
    assert canonical_regions == {"Korea", "Europe", "Taiwan", "Japan", "US"}
    assert unmapped_raw_regions == set()


@pytest.mark.skipif(not WORKBOOK.exists(), reason="TrackF (1).xlsx not present in this checkout")
def test_customer_casing_collision_in_the_real_file_resolves_to_one_spelling():
    import openpyxl

    wb = openpyxl.load_workbook(WORKBOOK, data_only=True)
    ws = wb["FCST_Revenue"]
    raw_customers = {row[1] for row in ws.iter_rows(min_row=5, max_col=2, values_only=True) if row[1]}

    # The real file: "Mobis" (rows 5-7) and "MOBIS" (rows 8-14) for the same account.
    assert {"Mobis", "MOBIS"}.issubset(raw_customers)

    canonical = {canonicalize_row({"customer": c}).canonical["customer"] for c in raw_customers}
    assert canonical == {"Mobis"}
