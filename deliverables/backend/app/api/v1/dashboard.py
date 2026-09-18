"""
Dashboard summary (WBS-adjacent, added for the UI build): the fixed set of
aggregates the Dashboards page needs in one round trip, computed live from the
same rows every other rollup endpoint reads -- no separate cache, no drift.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.opportunities import _to_read_model
from app.db.models.opportunity import Opportunity
from app.db.session import get_db
from app.schemas.rollup import DashboardSummary
from app.services.state_transitions import LOSS_VALUES, WIN_VALUES

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardSummary)
def get_dashboard(db: Session = Depends(get_db)) -> DashboardSummary:
    opps = list(db.scalars(select(Opportunity)).all())
    reads = [_to_read_model(o) for o in opps]

    total_k = sum(r.adjusted_revenue_k for r in reads)
    # Amount x confidence, which is what adjusted_revenue_k already is. This line
    # previously multiplied by confidence a second time, so the headline
    # "Weighted forecast" tile was reporting sales x confidence squared -- a
    # figure with no meaning that was always lower than the truth.
    #
    # It equals total_pipeline_k by construction today. Giving the forecast a
    # narrower scope than "every row" (excluding Lost, say) is a product
    # decision, not a defect fix, so it is not made here.
    weighted_k = sum(r.adjusted_revenue_k for r in reads)

    # Reported as its own figure. NRE is not silicon revenue, so it is never
    # added into total/open/won -- see app/calc/engine.py and WBS 3.5.
    nre_k = sum(r.nre_revenue_k for r in reads)
    open_k = won_k = 0.0
    funnel: dict[str, dict] = {}
    by_pl: dict[str, float] = {}
    by_year: dict[str, float] = {}

    for opp, read in zip(opps, reads):
        status = opp.design_status.strip().lower()
        if status in WIN_VALUES:
            won_k += read.adjusted_revenue_k
        elif status not in LOSS_VALUES:
            open_k += read.adjusted_revenue_k

        bucket = funnel.setdefault(opp.design_status, {"design_status": opp.design_status, "amount_k": 0.0, "count": 0})
        bucket["amount_k"] += read.adjusted_revenue_k
        bucket["count"] += 1

        pl_key = opp.product_line or "Unspecified"
        by_pl[pl_key] = by_pl.get(pl_key, 0.0) + read.adjusted_revenue_k

        year_key = str(opp.mp_date.year) if opp.mp_date else "No M/P date"
        by_year[year_key] = by_year.get(year_key, 0.0) + read.adjusted_revenue_k

    return DashboardSummary(
        total_pipeline_k=total_k,
        open_pipeline_k=open_k,
        weighted_forecast_k=weighted_k,
        closed_won_k=won_k,
        opportunity_count=len(opps),
        total_nre_revenue_k=nre_k,
        funnel_by_design_status=sorted(funnel.values(), key=lambda b: -b["amount_k"]),
        pipeline_by_product_line=by_pl,
        pipeline_by_mp_year=dict(sorted(by_year.items())),
    )
