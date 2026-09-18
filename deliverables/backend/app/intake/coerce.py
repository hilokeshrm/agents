"""
Coercion (WBS 3.3): `Dec'24` and `June'27` to dates, `TBD` to null, thousands
separators to float, percentages to fractions.

The done-when this module exists to satisfy: "Every coercion is reversible to
the source string, which is what the milestone factor must cite." Every function
here returns a CoercedValue carrying both the parsed value and the original raw
string, never just the parsed value alone -- a rubric factor citing a slipped
date has to quote what was actually written, not a parse of it.

TBD becomes null and is *reported* (via `note`), never defaulted to zero: seven
numeric fields in the real workbook carry TBD (docs/03-reference/
Opportunity_Tracking_Agent_Tab_and_Field_Map.docx, the Normalisation table), and a
zero there would silently deflate a regional total. The same file has a genuine
typo -- "Sop'26" for "Sep'26" -- in a milestone note; this module reports that as
unparseable rather than silently guessing the fix, the same discipline
app/intake/canonicalize.py applies to an unmapped region.

This is coercion only: it turns a raw cell into a typed value or explains why it
can't. Applying the WBS 2.2 enum maps to an already-coerced value is
app/intake/canonicalize.py's job, not this module's.
"""

import re
from dataclasses import dataclass
from datetime import date

NOT_A_VALUE = {"tbd", "n/a", ""}

# Both abbreviated ("Dec") and full ("June") spellings appear in the real file for
# the same field shape -- Funnel's M/P column uses "Dec'24"/"Nov'26"/"Sep'27"
# (abbreviated) while ProjectTrack's skeleton rows and other examples use full
# names like "June'27". A single strptime format string can't accept both.
_MONTH_NAMES = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

_MONTH_YEAR_RE = re.compile(r"^([A-Za-z]+)'(\d{2})$")


@dataclass(frozen=True)
class CoercedValue:
    raw: str
    value: object  # the coerced value, or None when not coercible / genuinely absent
    note: str = ""


def coerce_numeric(raw) -> CoercedValue:
    """Thousands separators to float; TBD/N/A to null, never zero."""
    raw_str = str(raw)
    key = raw_str.strip().lower()
    if key in NOT_A_VALUE:
        return CoercedValue(raw=raw_str, value=None, note=f"{raw_str!r} is not a number -- null, not zero")

    cleaned = raw_str.strip().replace(",", "")
    try:
        return CoercedValue(raw=raw_str, value=float(cleaned))
    except ValueError:
        return CoercedValue(raw=raw_str, value=None, note=f"{raw_str!r} does not parse as a number")


def coerce_percentage(raw) -> CoercedValue:
    """"50%" -> 0.5. A plain number is assumed already a fraction (the workbook's
    Confidence Level column stores 0.30/0.50/1.00 directly, never "50%")."""
    raw_str = str(raw)
    key = raw_str.strip().lower()
    if key in NOT_A_VALUE:
        return CoercedValue(raw=raw_str, value=None, note=f"{raw_str!r} is not a percentage -- null, not zero")

    stripped = raw_str.strip()
    if stripped.endswith("%"):
        numeric = coerce_numeric(stripped[:-1])
        if numeric.value is None:
            return CoercedValue(raw=raw_str, value=None, note=numeric.note)
        return CoercedValue(raw=raw_str, value=numeric.value / 100.0)

    return coerce_numeric(stripped)


def coerce_date(raw) -> CoercedValue:
    """"Dec'24" / "June'27" -> the first of that month. TBD/N/A -> null. A token
    that looks like the "Month'YY" shape but names no real month -- the file's
    own "Sop'26" typo -- is reported as unparseable, not silently corrected to
    what it probably meant."""
    raw_str = str(raw)
    key = raw_str.strip().lower()
    if key in NOT_A_VALUE:
        return CoercedValue(raw=raw_str, value=None, note=f"{raw_str!r} is not a date -- null, not a guessed one")

    match = _MONTH_YEAR_RE.match(raw_str.strip())
    if not match:
        return CoercedValue(raw=raw_str, value=None, note=f"{raw_str!r} does not match the Month'YY shape")

    month_name, year_digits = match.groups()
    month = _MONTH_NAMES.get(month_name.lower())
    if month is None:
        return CoercedValue(
            raw=raw_str, value=None,
            note=f"{raw_str!r} has the Month'YY shape but {month_name!r} is not a real month name",
        )

    year = 2000 + int(year_digits)
    return CoercedValue(raw=raw_str, value=date(year, month, 1))
