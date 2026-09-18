"""
Accounts (WBS-adjacent, added for the UI build): not a stored entity. An account
is every distinct Opportunity.customer value, grouped and rolled up live -- there
is no accounts table, so a customer name typo in one opportunity and not another
would (correctly) show up as two separate accounts here rather than being
silently merged. That is a real data-quality signal, not a bug to paper over.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.opportunities import _to_read_model
from app.db.models.opportunity import Opportunity
from app.db.session import get_db
from app.schemas.rollup import AccountDetail, AccountSummary
from app.services.state_transitions import LOSS_VALUES, WIN_VALUES

router = APIRouter(prefix="/accounts", tags=["accounts"])


def _pipeline_totals(opps: list[Opportunity]) -> tuple[float, float]:
    """Returns (open_pipeline_k, closed_won_k) using each opportunity's current
    adjusted revenue -- same figure the calc engine computes everywhere else."""
    open_k = won_k = 0.0
    for opp in opps:
        read = _to_read_model(opp)
        status = opp.design_status.strip().lower()
        if status in WIN_VALUES:
            won_k += read.adjusted_revenue_k
        elif status in LOSS_VALUES:
            pass  # closed lost: not open pipeline, not a win
        else:
            open_k += read.adjusted_revenue_k
    return open_k, won_k


@router.get("", response_model=list[AccountSummary])
def list_accounts(db: Session = Depends(get_db)) -> list[AccountSummary]:
    all_opps = list(db.scalars(select(Opportunity)).all())
    by_customer: dict[str, list[Opportunity]] = {}
    for opp in all_opps:
        by_customer.setdefault(opp.customer, []).append(opp)

    summaries = []
    for name, opps in sorted(by_customer.items()):
        open_k, won_k = _pipeline_totals(opps)
        summaries.append(AccountSummary(
            name=name,
            end_customers=sorted({o.end_customer for o in opps}),
            regions=sorted({o.region for o in opps}),
            opportunity_count=len(opps),
            open_pipeline_k=open_k,
            closed_won_k=won_k,
        ))
    return summaries


@router.get("/{name}", response_model=AccountDetail)
def get_account(name: str, db: Session = Depends(get_db)) -> AccountDetail:
    opps = list(db.scalars(select(Opportunity).where(Opportunity.customer == name)).all())
    if not opps:
        raise HTTPException(status_code=404, detail="Account not found")

    reads = [_to_read_model(o) for o in opps]
    open_k, won_k = _pipeline_totals(opps)
    weighted_k = sum(r.adjusted_revenue_k * o.confidence for r, o in zip(reads, opps))

    by_pl: dict[str, float] = {}
    for opp, read in zip(opps, reads):
        key = opp.product_line or "Unspecified"
        by_pl[key] = by_pl.get(key, 0.0) + read.adjusted_revenue_k

    return AccountDetail(
        name=name,
        end_customers=sorted({o.end_customer for o in opps}),
        regions=sorted({o.region for o in opps}),
        opportunity_count=len(opps),
        open_pipeline_k=open_k,
        closed_won_k=won_k,
        opportunities=reads,
        pipeline_by_product_line=by_pl,
        weighted_k=weighted_k,
        parts_in_play=len({o.part_number for o in opps}),
    )
