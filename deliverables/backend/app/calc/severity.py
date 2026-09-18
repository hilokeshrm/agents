"""
Blocking vs advisory severity (WBS 4.2): a blocking finding excludes a row from
roll-up totals and counts it separately; an advisory one annotates and lets the
row through. The distinction matters more than it sounds -- a design win worth
zero silently included in a weighted total is how a forecast becomes wrong
without anyone editing a number, and it is exactly what ProjectTrack rows 14-18
are: Design Win / Promotion rows with a Region, a Design Status and an EAU, but
no Customer, no Project, no Disty ASP and no Confidence
(docs/03-reference/Opportunity_Tracking_Agent_Tab_and_Field_Map.docx, section 2).

No specific rule set (WBS 4.1, still to do) feeds this yet -- this is the general
mechanism, the same way app/registry/runnable.py preceded any real analysis or
rubric factor consuming it. classify_severity below is a minimal, real example
rule (missing Customer or Disty ASP is blocking), not the WBS 4.1 rule set.

A blocking row is never passed to app/calc/engine.py's compute_project_financials
at all -- it may be missing exactly what that function needs (Disty ASP), so
"excluded from the roll-up" here means "never computed," not "computed then
discarded."
"""

from app.calc.engine import compute_project_financials, portfolio_rollup

BLOCKING = "blocking"
ADVISORY = "advisory"

# A row missing either of these cannot have Sales Revenue computed at all
# (compute_project_financials multiplies eau_kpcs by disty_asp), so it is
# blocking, not merely advisory. Real example: ProjectTrack rows 14-18.
_REQUIRED_FOR_REVENUE = ("customer", "disty_asp")


def classify_severity(row: dict) -> str | None:
    if any(row.get(field) is None for field in _REQUIRED_FOR_REVENUE):
        return BLOCKING
    return None


def rollup_with_severity(rows_with_severity: list) -> dict:
    """rows_with_severity: (raw_row, severity) pairs, severity in (BLOCKING,
    ADVISORY, None). Done-when: an included total, an excluded count, and the
    two never blend."""
    included_financials = []
    excluded_count = 0
    advisory_count = 0

    for row, severity in rows_with_severity:
        if severity == BLOCKING:
            excluded_count += 1
            continue
        included_financials.append(compute_project_financials(row))
        if severity == ADVISORY:
            advisory_count += 1

    rollup = portfolio_rollup(included_financials)
    return {
        "included_total_sales_revenue_k": rollup["total_sales_revenue_k"],
        "included_total_adjusted_revenue_k": rollup["total_adjusted_revenue_k"],
        "included_count": len(included_financials),
        "excluded_count": excluded_count,
        "advisory_count": advisory_count,
    }
