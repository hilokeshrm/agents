"""
Scenario recompute (WBS 5.7) and the forecast feed (the finance landing view,
and the ROI Agent's input over MCP later).

A scenario is pure: it writes nothing, persists nothing, and returns the same
calc-engine output the dashboard renders, called a second time with different
confidences. That is the whole contract -- if a scenario used a different
function from the base case, the delta between them would not mean anything.

The forecast feed states its own assumption instead of hiding it. The quarterly
phasing rule (flat / ramp from M/P / programme-driven) is WBS 5.5 and undecided,
so this feed does not spread a row's revenue across quarters. It recognises each
row's weighted revenue in the quarter its M/P date falls in, says so in the
response, and reports rows with no M/P date as unphased rather than dropping them
into the nearest quarter to make the total look complete.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.services.financials import adjusted_revenue_k, financials_for
from app.calc.phasing import PROGRAMME, RAMP, UNPHASED, phase
from app.db.models.opportunity import Opportunity
from app.db.models.proposal import Proposal
from app.db.session import get_db
from app.security.roles import Actor, current_actor, require, scope_opportunities

router = APIRouter(tags=["scenarios"])


class Override(BaseModel):
    opportunity_id: str
    confidence: float


class ScenarioRequest(BaseModel):
    overrides: list[Override] = []
    # Fold in every pending proposal's proposed value -- "what is the weighted
    # pipeline if I approve everything in the queue?"
    include_pending_proposals: bool = False


class ScenarioRow(BaseModel):
    opportunity_id: str
    project: str
    region: str
    base_confidence: float
    scenario_confidence: float
    base_adjusted_revenue_k: float
    scenario_adjusted_revenue_k: float
    delta_k: float
    source: str  # override | pending proposal


class ScenarioRead(BaseModel):
    base_weighted_k: float
    scenario_weighted_k: float
    delta_k: float
    base_by_region: dict[str, float]
    scenario_by_region: dict[str, float]
    changed_rows: list[ScenarioRow]
    rows_considered: int
    note: str


def _row(opp: Opportunity, confidence: float) -> float:
    return adjusted_revenue_k(opp, confidence)


@router.post("/scenarios/recompute", response_model=ScenarioRead)
def recompute(
    payload: ScenarioRequest,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
) -> ScenarioRead:
    rows = list(db.scalars(scope_opportunities(select(Opportunity), Opportunity, actor)).all())
    by_id = {o.id: o for o in rows}

    scenario: dict[str, tuple[float, str]] = {}
    if payload.include_pending_proposals:
        for proposal in db.scalars(select(Proposal).where(Proposal.status == "pending")).all():
            if proposal.opportunity_id in by_id:
                scenario[proposal.opportunity_id] = (proposal.proposed_confidence, "pending proposal")
    for override in payload.overrides:
        if override.opportunity_id in by_id:
            scenario[override.opportunity_id] = (override.confidence, "override")

    base_total = scenario_total = 0.0
    base_by_region: dict[str, float] = {}
    scenario_by_region: dict[str, float] = {}
    changed: list[ScenarioRow] = []

    for opp in rows:
        base_k = _row(opp, opp.confidence)
        new_confidence, source = scenario.get(opp.id, (opp.confidence, ""))
        scenario_k = base_k if source == "" else _row(opp, new_confidence)

        base_total += base_k
        scenario_total += scenario_k
        base_by_region[opp.region] = base_by_region.get(opp.region, 0.0) + base_k
        scenario_by_region[opp.region] = scenario_by_region.get(opp.region, 0.0) + scenario_k

        if source:
            changed.append(ScenarioRow(
                opportunity_id=opp.id, project=opp.project, region=opp.region,
                base_confidence=opp.confidence, scenario_confidence=new_confidence,
                base_adjusted_revenue_k=base_k, scenario_adjusted_revenue_k=scenario_k,
                delta_k=scenario_k - base_k, source=source,
            ))

    changed.sort(key=lambda r: abs(r.delta_k), reverse=True)
    return ScenarioRead(
        base_weighted_k=base_total, scenario_weighted_k=scenario_total,
        delta_k=scenario_total - base_total,
        base_by_region=base_by_region, scenario_by_region=scenario_by_region,
        changed_rows=changed, rows_considered=len(rows),
        note="computed by app/calc/engine.py, the same function that produced the dashboard figure; "
             "nothing was written",
    )


class ForecastQuarter(BaseModel):
    year: int
    quarter: int
    label: str
    weighted_revenue_k: float
    sales_revenue_k: float
    opportunity_count: int
    # Non-recurring engineering, kept in its own column. It is recognised whole
    # in the M/P quarter rather than spread over the ramp: the ramp models
    # silicon shipping into a programme, and a one-off engineering charge does
    # not ramp (WBS 3.5; app/calc/nre.py).
    nre_revenue_k: float = 0.0
    nre_weighted_k: float = 0.0


class ForecastFeedRead(BaseModel):
    quarters: list[ForecastQuarter]
    unphased_weighted_k: float
    unphased_count: int
    total_weighted_k: float
    total_nre_revenue_k: float
    total_nre_weighted_k: float
    unphased_nre_k: float
    phasing_rule: str
    nre_rule: str
    note: str
    # How many rows were phased on each basis (WBS 5.5): programme profile,
    # M/P ramp, or left unphased.
    basis_counts: dict[str, int] = {}


@router.get("/forecast-feed", response_model=ForecastFeedRead)
def forecast_feed(
    db: Session = Depends(get_db),
    actor: Actor = Depends(require("pull_forecast_feed")),
) -> ForecastFeedRead:
    rows = db.scalars(scope_opportunities(select(Opportunity), Opportunity, actor)).all()
    buckets: dict[tuple[int, int], ForecastQuarter] = {}
    unphased_k = 0.0
    unphased_count = 0
    unphased_nre = 0.0
    total = 0.0
    total_nre = 0.0
    total_nre_weighted = 0.0

    def bucket_for(year: int, quarter: int) -> ForecastQuarter:
        key = (year, quarter)
        bucket = buckets.get(key)
        if bucket is None:
            bucket = ForecastQuarter(
                year=year, quarter=quarter, label=f"{year} Q{quarter}",
                weighted_revenue_k=0.0, sales_revenue_k=0.0, opportunity_count=0,
            )
            buckets[key] = bucket
        return bucket

    basis_counts = {PROGRAMME: 0, RAMP: 0, UNPHASED: 0}
    for opp in rows:
        financials = financials_for(opp)
        total += financials.adjusted_revenue_k
        total_nre += financials.nre_revenue_k
        total_nre_weighted += financials.nre_weighted_k

        profile = {int(k): v for k, v in (opp.phasing_profile or {}).items()} or None
        phasing = phase(eau_kpcs=opp.eau_kpcs, mp_date=opp.mp_date, profile=profile)
        basis_counts[phasing.basis] += 1
        if phasing.basis == UNPHASED:
            unphased_k += financials.adjusted_revenue_k
            unphased_nre += financials.nre_revenue_k
            unphased_count += 1
            continue

        for q in phasing.quarters:
            bucket = bucket_for(q.year, q.quarter)
            bucket.weighted_revenue_k += financials.adjusted_revenue_k * q.fraction
            bucket.sales_revenue_k += financials.sales_revenue_k * q.fraction
            bucket.opportunity_count += 1

        # Whole, in the opening quarter -- not spread across the ramp.
        if financials.nre_revenue_k:
            first = phasing.quarters[0]
            opening = bucket_for(first.year, first.quarter)
            opening.nre_revenue_k += financials.nre_revenue_k
            opening.nre_weighted_k += financials.nre_weighted_k

    return ForecastFeedRead(
        quarters=[buckets[k] for k in sorted(buckets)],
        unphased_weighted_k=unphased_k, unphased_count=unphased_count, total_weighted_k=total,
        total_nre_revenue_k=total_nre, total_nre_weighted_k=total_nre_weighted,
        unphased_nre_k=unphased_nre,
        phasing_rule="programme_profile > mp_date_ramp_10_20_30_40 > unphased",
        nre_rule="recognised_whole_at_mp_quarter",
        basis_counts=basis_counts,
        note="Decision #65: a row with a programme volume profile is phased on it; otherwise silicon "
             "volume revenue is phased across the M/P quarter and the next three using 10%, 20%, 30%, "
             "40%; rows with neither remain unphased and are reported as such. "
             "NRE is reported in its own column and never added into the volume figures: it is "
             "recognised whole in the M/P quarter, because a one-off engineering charge does not "
             "ramp. Both the entered charge and a confidence-weighted view are returned, since "
             "whether an unwon design's NRE should be weighted is not a decision this code makes.",
    )
