"""
Reports (WBS-adjacent, added for the UI build): a small set of canned groupings
over the live opportunity set. Each report groups the same rows a different way
and reports a total per group -- no new storage, no invented dimensions; every
group key is a real column already on Opportunity.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.opportunities import _to_read_model
from app.db.models.opportunity import Opportunity
from app.db.session import get_db
from app.schemas.rollup import ReportResult, ReportRow

router = APIRouter(prefix="/reports", tags=["reports"])

REPORT_DEFS = {
    "design_status": ("Opportunities by Design Status", lambda o: o.design_status),
    "stage": ("Opportunities by Stage", lambda o: o.stage),
    "product_line": ("Pipeline by Product Line", lambda o: o.product_line or "Unspecified"),
    "region": ("Pipeline by Region", lambda o: o.region),
    "competitor": ("Pipeline by Named Competitor", lambda o: o.competitor_part or "No competitor named"),
    "mp_year": ("Pipeline by Mass-Production Year", lambda o: str(o.mp_date.year) if o.mp_date else "No M/P date"),
}


@router.get("")
def list_reports() -> list[dict]:
    return [{"id": rid, "name": name} for rid, (name, _) in REPORT_DEFS.items()]


@router.get("/{report_id}", response_model=ReportResult)
def run_report(report_id: str, db: Session = Depends(get_db)) -> ReportResult:
    if report_id not in REPORT_DEFS:
        raise HTTPException(status_code=404, detail=f"No such report: {report_id!r}")
    name, key_fn = REPORT_DEFS[report_id]

    all_opps = list(db.scalars(select(Opportunity)).all())
    grouped: dict[str, list[Opportunity]] = {}
    for opp in all_opps:
        grouped.setdefault(key_fn(opp), []).append(opp)

    rows = []
    grand_total = 0.0
    for key, opps in sorted(grouped.items()):
        reads = [_to_read_model(o) for o in opps]
        group_total = sum(r.adjusted_revenue_k for r in reads)
        grand_total += group_total
        rows.append(ReportRow(
            group=key, opportunity_count=len(opps), total_amount_k=group_total, opportunities=reads,
        ))

    return ReportResult(
        report_id=report_id, name=name, groups=rows,
        grand_total_k=grand_total, record_count=len(all_opps),
    )
