"""
Regression tests for coercion (WBS 3.3).

test_real_mp_dates_from_the_workbook_coerce reads the actual TrackF (1).xlsx
Funnel M/P column directly (same approach as test_canonicalize_intake.py) --
every real value there coerces cleanly except TBD, which is null by design.
"""

from datetime import date
from pathlib import Path

import pytest

from app.intake.coerce import coerce_date, coerce_numeric, coerce_percentage

WORKBOOK = Path(__file__).resolve().parents[3] / "data" / "TrackF (1).xlsx"


def test_coerce_date_abbreviated_month():
    result = coerce_date("Dec'24")
    assert result.value == date(2024, 12, 1)
    assert result.raw == "Dec'24"


def test_coerce_date_full_month_name():
    """The real file mixes abbreviated ("Dec'24") and full ("June'27") spellings
    for the same field shape -- both must parse."""
    result = coerce_date("June'27")
    assert result.value == date(2027, 6, 1)


def test_coerce_date_tbd_is_null_not_guessed():
    result = coerce_date("TBD")
    assert result.value is None
    assert "not a guessed one" in result.note
    assert result.raw == "TBD"  # reversible: the source string survives even when unparseable


def test_coerce_date_na_is_null():
    assert coerce_date("N/A").value is None


def test_coerce_date_reports_the_real_files_typo_rather_than_fixing_it():
    """"Sop'26" is a genuine typo for "Sep'26" in the source document (Funnel's
    Next Action To Do free text). Silently correcting it would be inventing a
    value the file does not actually contain -- it must come back unparseable."""
    result = coerce_date("Sop'26")
    assert result.value is None
    assert "Sop" in result.note


def test_coerce_date_rejects_unrelated_text():
    result = coerce_date("not a date at all")
    assert result.value is None


def test_coerce_numeric_thousands_separator():
    result = coerce_numeric("1,343")
    assert result.value == 1343.0


def test_coerce_numeric_plain_value_passthrough():
    assert coerce_numeric(1100).value == 1100.0
    assert coerce_numeric("57175").value == 57175.0


def test_coerce_numeric_tbd_is_null_not_zero():
    """The done-when this guards directly: TBD must never become 0, which would
    silently deflate a regional total."""
    result = coerce_numeric("TBD")
    assert result.value is None
    assert result.value != 0


def test_coerce_percentage_from_percent_string():
    result = coerce_percentage("50%")
    assert result.value == pytest.approx(0.5)


def test_coerce_percentage_plain_fraction_passthrough():
    """The workbook's own Confidence Level column stores 0.30/0.50/1.00 directly,
    never as a "%" string -- a plain number must pass through unchanged."""
    assert coerce_percentage(0.3).value == pytest.approx(0.3)
    assert coerce_percentage("1.0").value == pytest.approx(1.0)


def test_coerce_percentage_tbd_is_null():
    assert coerce_percentage("TBD").value is None


@pytest.mark.skipif(not WORKBOOK.exists(), reason="TrackF (1).xlsx not present in this checkout")
def test_real_mp_dates_from_the_workbook_coerce():
    import openpyxl

    wb = openpyxl.load_workbook(WORKBOOK, data_only=True)
    ws = wb["Funnel"]
    # Column I ("M/P") on Funnel, real data rows only (5-12; see test_canonicalize_intake.py).
    raw_values = [row[0] for row in ws.iter_rows(min_row=5, max_row=12, min_col=9, max_col=9, values_only=True) if row[0]]

    assert "TBD" in raw_values  # row 11's placeholder, per the field map doc
    assert len(raw_values) >= 7

    results = [coerce_date(v) for v in raw_values]
    tbd_results = [r for r in results if r.raw == "TBD"]
    real_date_results = [r for r in results if r.raw != "TBD"]

    assert all(r.value is None for r in tbd_results)
    assert all(r.value is not None for r in real_date_results), [
        (r.raw, r.note) for r in real_date_results if r.value is None
    ]
