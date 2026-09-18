"""
Milestone extractor (WBS 6.3): pulls PPAP, ES, Design Review and SoP dates out
of Funnel's free-text "Next Action To Do" column into real date fields, then
flags what is overdue or missing a date. Real example (docs/03-reference/
Opportunity_Tracking_Agent_Tab_and_Field_Map.docx, table 3, Funnel column Q):
"NX5 SoP: Sop'26. Design Review: Jul'25, PPAP: Oct'26" -- Design Review and PPAP
parse cleanly; SoP does not, because "Sop'26" is the file's own typo for
"Sep'26". Reuses app/intake/coerce.py's coerce_date for the actual parse, so
that typo is reported the same way there, not silently guessed here.

The done-when: every date this module claims can be traced back to the exact
substring it came from. A MilestoneEvent always carries source_substring, the
literal text it was extracted from, not just the parsed date -- the rubric
factor that cites a slip must quote what was written, never a parse of it (same
discipline as coerce.py's CoercedValue.raw).

overdue is computed against an as_of date passed in by the caller, never
datetime.now() read inside this module -- keeps extraction pure and every test
reproducible regardless of what day it happens to run.
"""

import re
from dataclasses import dataclass
from datetime import date

from app.intake.coerce import coerce_date

MILESTONES = ("PPAP", "ES", "Design Review", "SoP")

# \b boundaries matter here: "ES" is a real substring of "DESIGN" (as in "Design
# Review"), and without word boundaries a naive containment check would flag
# every Design Review mention as an ES milestone too.
_MILESTONE_RE = re.compile(
    r"\b(" + "|".join(re.escape(m) for m in MILESTONES) + r")\b\s*:\s*([A-Za-z]+'\d{2})"
)


@dataclass(frozen=True)
class MilestoneEvent:
    milestone: str
    source_substring: str  # e.g. "SoP: Sop'26" -- the exact text the claim traces to
    raw_date: str  # e.g. "Sop'26"
    parsed_date: date | None  # None when raw_date doesn't actually parse
    overdue: bool
    note: str = ""


def extract_milestones(text: str, as_of: date) -> list[MilestoneEvent]:
    if not text:
        return []

    events: list[MilestoneEvent] = []
    for match in _MILESTONE_RE.finditer(text):
        milestone, raw_date = match.groups()
        coerced = coerce_date(raw_date)
        overdue = coerced.value is not None and coerced.value < as_of
        events.append(MilestoneEvent(
            milestone=milestone,
            source_substring=match.group(0),
            raw_date=raw_date,
            parsed_date=coerced.value,
            overdue=overdue,
            note=coerced.note,
        ))

    matched_milestones = {e.milestone for e in events}
    for milestone in MILESTONES:
        if milestone in matched_milestones:
            continue
        if re.search(r"\b" + re.escape(milestone) + r"\b", text):
            events.append(MilestoneEvent(
                milestone=milestone, source_substring=milestone, raw_date="",
                parsed_date=None, overdue=False, note=f"{milestone} named but no date follows it",
            ))

    return events
