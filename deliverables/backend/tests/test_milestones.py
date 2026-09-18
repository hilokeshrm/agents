"""
Regression tests for the milestone extractor (WBS 6.3).

test_real_funnel_next_action_text reads the actual Funnel "Next Action To Do"
column directly from TrackF (1).xlsx (same approach as the other real-file
tests) rather than transcribing the cell text by hand.
"""

from datetime import date
from pathlib import Path

import pytest

from app.intake.milestones import extract_milestones

WORKBOOK = Path(__file__).resolve().parents[3] / "data" / "TrackF (1).xlsx"

AS_OF = date(2026, 8, 31)  # today, per this session's context -- passed explicitly, never read from the clock


def test_extracts_parseable_milestone_with_exact_source_substring():
    events = extract_milestones("Design Review: Jul'25", AS_OF)
    assert len(events) == 1
    e = events[0]
    assert e.milestone == "Design Review"
    assert e.raw_date == "Jul'25"
    assert e.parsed_date == date(2025, 7, 1)
    assert e.source_substring == "Design Review: Jul'25"  # traceable to the exact text, per the done-when


def test_flags_overdue_relative_to_as_of():
    events = extract_milestones("PPAP: Jan'20", AS_OF)
    assert events[0].overdue is True

    future = extract_milestones("PPAP: Jan'30", AS_OF)
    assert future[0].overdue is False


def test_unparseable_date_is_reported_not_guessed():
    """The real file's own typo, in isolation: "Sop'26" is not a date the
    extractor may silently correct to "Sep'26"."""
    events = extract_milestones("SoP: Sop'26", AS_OF)
    assert len(events) == 1
    e = events[0]
    assert e.milestone == "SoP"
    assert e.raw_date == "Sop'26"
    assert e.parsed_date is None
    assert e.overdue is False  # cannot be overdue if it was never a date to begin with
    assert "does not match" in e.note or "not a real month" in e.note


def test_milestone_named_but_no_date_is_flagged_missing():
    events = extract_milestones("ES is still pending", AS_OF)
    assert len(events) == 1
    assert events[0].milestone == "ES"
    assert events[0].parsed_date is None
    assert "no date follows" in events[0].note


def test_design_review_does_not_false_positive_as_es():
    """"ES" is a literal substring of "DESIGN" -- a naive containment check
    would wrongly flag every Design Review mention as an ES milestone too."""
    events = extract_milestones("Design Review: Jul'25", AS_OF)
    assert {e.milestone for e in events} == {"Design Review"}


def test_no_milestones_in_plain_text():
    assert extract_milestones("Under evaluation, no specific dates yet.", AS_OF) == []


def test_empty_text():
    assert extract_milestones("", AS_OF) == []
    assert extract_milestones(None, AS_OF) == []


@pytest.mark.skipif(not WORKBOOK.exists(), reason="TrackF (1).xlsx not present in this checkout")
def test_real_funnel_next_action_text():
    import openpyxl

    wb = openpyxl.load_workbook(WORKBOOK, data_only=True)
    ws = wb["Funnel"]
    # Column Q ("Next Action To Do") on Funnel, real data rows (see test_canonicalize_intake.py).
    texts = [row[0] for row in ws.iter_rows(min_row=5, max_row=12, min_col=17, max_col=17, values_only=True) if row[0]]

    assert texts, "expected at least one real Next Action To Do cell"

    all_events = [e for text in texts for e in extract_milestones(text, AS_OF)]
    by_milestone = {}
    for e in all_events:
        by_milestone.setdefault(e.milestone, []).append(e)

    # The row cited in docs/03-reference/Opportunity_Tracking_Agent_Tab_and_Field_Map.docx:
    # "NX5 SoP: Sop'26. Design Review: Jul'25, PPAP: Oct'26".
    sop_events = [e for e in by_milestone.get("SoP", []) if e.raw_date == "Sop'26"]
    assert sop_events, "expected the real file's SoP: Sop'26 text to be extracted"
    assert sop_events[0].parsed_date is None  # the typo, reported, not corrected

    design_review_events = [e for e in by_milestone.get("Design Review", []) if e.raw_date == "Jul'25"]
    assert design_review_events
    assert design_review_events[0].parsed_date == date(2025, 7, 1)

    ppap_events = [e for e in by_milestone.get("PPAP", []) if e.raw_date == "Oct'26"]
    assert ppap_events
    assert ppap_events[0].parsed_date == date(2026, 10, 1)

    # Every claimed date traces back to source text actually present in the cell it came from.
    for text in texts:
        for e in extract_milestones(text, AS_OF):
            assert e.source_substring in text
