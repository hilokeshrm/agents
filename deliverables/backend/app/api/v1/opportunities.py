"""
Opportunity intake and read endpoints. Direct UI entry is the primary path
(see [[opptrack-intake-not-excel]]); bulk import and CRM sync are separate
routers that funnel into the same guards (app/guards/) and calc engine.

Financials (sales_revenue_k, adjusted_revenue_k) are never persisted columns --
they are recomputed from app/calc/engine.py on every read, so the base case and
the calibrated case stay the same function called twice (WBS 5.0).

create_opportunity canonicalizes (WBS 3.4) before persisting and attaches
provenance to every value (WBS 3.6) -- guards beyond that (WBS 4.0) still land
separately; this is not full intake validation, only "no value reaches the calc
engine without a source and a trust level attached."
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.services.financials import financials_for
from app.db.models.field_value import TRUST_LEVELS
from app.db.models.field_value import FieldValue as FieldValueRow
from app.db.models.opportunity import Opportunity
from app.db.models.owner_history import OwnerHistory
from app.db.models.state_history import StateHistory
from app.db.session import get_db
from app.registry.enums import canonicalize_region
from app.intake.canonicalize import canonicalize_row
from app.intake.provenance import wrap_row
from app.registry.parameters import PARAMS
from app.schemas.opportunity import OpportunityCreate, OpportunityRead
from app.schemas.state_history import OwnerChangeCreate, OwnerEventRead, StateEventRead, StateTransitionCreate, WinRateRead
from app.security.roles import Actor, assert_visible, current_actor, require, scope_opportunities
from app.services.state_transitions import (
    APPROVAL_REQUIRED_STATUSES,
    record_transition,
    seed_initial_state,
    time_in_current_stage,
    win_rate,
)
from app.services.intake import IntakeError, create_opportunity as create_opportunity_service

router = APIRouter(prefix="/opportunities", tags=["opportunities"])


def _to_read_model(opp: Opportunity) -> OpportunityRead:
    financials = financials_for(opp)
    return OpportunityRead(
        id=opp.id,
        external_id=opp.external_id,
        region=opp.region,
        customer=opp.customer,
        end_customer=opp.end_customer,
        project=opp.project,
        application=opp.application,
        product_line=opp.product_line,
        part_number=opp.part_number,
        design_status=opp.design_status,
        stage=opp.stage,
        mp_date=opp.mp_date,
        eau_kpcs=opp.eau_kpcs,
        unit_set=opp.unit_set,
        disty_asp=opp.disty_asp,
        resale_asp=opp.resale_asp,
        confidence=opp.confidence,
        competitor_part=opp.competitor_part,
        owner=opp.owner,
        evidence=opp.evidence,
        confidence_rationale=opp.confidence_rationale,
        nre_charge_k=opp.nre_charge_k,
        sales_revenue_k=financials.sales_revenue_k,
        adjusted_revenue_k=financials.adjusted_revenue_k,
        nre_revenue_k=financials.nre_revenue_k,
        nre_weighted_k=financials.nre_weighted_k,
        set_volume=financials.set_volume,
        attach_rate=financials.attach_rate,
        channel_margin_usd=financials.channel_margin_usd,
        channel_margin_pct=financials.channel_margin_pct,
    )


@router.post("", response_model=OpportunityRead, status_code=201)
def create_opportunity(
    payload: OpportunityCreate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require("create_edit_opportunity")),
) -> OpportunityRead:
    """Direct entry -- the primary intake path -- through the one intake
    service every source uses (WBS 3.7): canonicalise, Matrix A pairing check
    (V-b), calculation fields required, advisory findings for the rest,
    OPP-000001 minted, provenance written, state and owner streams seeded."""
    # Enforcement point 2 on the way in as well as out: a region-scoped person
    # cannot create a row they would then be unable to see.
    region = canonicalize_region(payload.region) or payload.region
    if not actor.in_scope(region):
        raise HTTPException(status_code=403, detail=f"{actor.user_id!r} is scoped to {list(actor.regions)}; cannot create a row in {region!r}")
    try:
        result = create_opportunity_service(
            db, payload.model_dump(), source="direct_entry",
            trust=TRUST_LEVELS["direct_entry"], actor=actor.user_id,
        )
    except IntakeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    db.commit()
    db.refresh(result.opportunity)
    read = _to_read_model(result.opportunity)
    read.intake_advisories = result.advisories
    return read


@router.get("", response_model=list[OpportunityRead])
def list_opportunities(
    db: Session = Depends(get_db), actor: Actor = Depends(current_actor)
) -> list[OpportunityRead]:
    """Region scope is applied to the query, not to the response (WBS 9.5,
    enforcement point 2): an out-of-scope row is never fetched, so there is no
    filtered list for a bug to leak."""
    stmt = scope_opportunities(select(Opportunity), Opportunity, actor).order_by(
        Opportunity.created_at.desc()
    )
    return [_to_read_model(opp) for opp in db.scalars(stmt).all()]


@router.get("/{opportunity_id}", response_model=OpportunityRead)
def get_opportunity(
    opportunity_id: str, db: Session = Depends(get_db), actor: Actor = Depends(current_actor)
) -> OpportunityRead:
    return _to_read_model(_get_or_404(db, opportunity_id, actor))


def _get_or_404(db: Session, opportunity_id: str, actor: Actor | None = None) -> Opportunity:
    opp = db.get(Opportunity, opportunity_id) or db.scalar(
        select(Opportunity).where(Opportunity.external_id == opportunity_id)
    )
    if opp is None:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    if actor is not None:
        # 404 rather than 403: a 403 confirms the row exists, which is itself a
        # disclosure when the data is unannounced design wins and pricing.
        assert_visible(opp.region, actor)
    return opp


@router.post("/{opportunity_id}/owner", response_model=OwnerEventRead, status_code=201)
def change_owner(
    opportunity_id: str,
    payload: OwnerChangeCreate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require("create_edit_opportunity")),
) -> OwnerEventRead:
    opp = _get_or_404(db, opportunity_id, actor)
    owner = payload.owner.strip()
    if not owner:
        raise HTTPException(status_code=400, detail="owner is required")
    if owner == opp.owner:
        raise HTTPException(status_code=409, detail="owner is already assigned")
    event = OwnerHistory(
        opportunity_id=opp.id, from_owner=opp.owner, to_owner=owner, actor=payload.actor.strip() or actor.user_id,
    )
    opp.owner = owner
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


@router.get("/{opportunity_id}/owner-history", response_model=list[OwnerEventRead])
def get_owner_history(
    opportunity_id: str, db: Session = Depends(get_db), actor: Actor = Depends(current_actor)
) -> list[OwnerEventRead]:
    opp = _get_or_404(db, opportunity_id, actor)
    return list(db.scalars(
        select(OwnerHistory).where(OwnerHistory.opportunity_id == opp.id).order_by(OwnerHistory.occurred_at, OwnerHistory.id)
    ).all())


@router.post("/{opportunity_id}/transition", response_model=StateEventRead, status_code=201)
def transition_opportunity(
    opportunity_id: str,
    payload: StateTransitionCreate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require("move_stage_status")),
) -> StateEventRead:
    """A moved card (stage board drag, or a design-status change) calls this rather
    than PATCHing the opportunity row directly -- record_transition is the only
    sanctioned write path for these two fields (WBS 9.2)."""
    opp = _get_or_404(db, opportunity_id, actor)
    if payload.field == "design_status" and payload.to_value.lower() in APPROVAL_REQUIRED_STATUSES:
        if not actor.can_act_on_region("close_design_lost", opp.region):
            raise HTTPException(
                status_code=403,
                detail="Mass Production and Design Lost transitions require manager or director approval",
            )
    try:
        event = record_transition(
            db, opp, field=payload.field, to_value=payload.to_value,
            actor=payload.actor, reason_code=payload.reason_code,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    db.commit()
    db.refresh(event)
    return event


@router.get("/{opportunity_id}/state-history", response_model=list[StateEventRead])
def get_state_history(
    opportunity_id: str, db: Session = Depends(get_db), actor: Actor = Depends(current_actor)
) -> list[StateEventRead]:
    _get_or_404(db, opportunity_id, actor)
    stmt = (
        select(StateHistory)
        .where(StateHistory.opportunity_id == opportunity_id)
        .order_by(StateHistory.occurred_at)
    )
    return list(db.scalars(stmt).all())


@router.get("/{opportunity_id}/provenance")
def get_provenance(
    opportunity_id: str, db: Session = Depends(get_db), actor: Actor = Depends(current_actor)
) -> list[dict]:
    """Where each value came from (WBS 3.6). The question a reviewer asks about a
    surprising number is always who put that there, and field_value is the only
    place that answers it -- the opportunity row carries the value, not its source.

    Returns the highest-trust value per parameter, with the losers alongside:
    a connector never silently overwrites a human edit, so a disagreement has to
    be visible rather than resolved by whichever wrote last."""
    opp = _get_or_404(db, opportunity_id, actor)
    rows = db.scalars(
        select(FieldValueRow)
        .where(FieldValueRow.opportunity_id == opp.id)
        .order_by(FieldValueRow.trust.desc(), FieldValueRow.captured_at.desc())
    ).all()

    by_param: dict[str, dict] = {}
    for row in rows:
        entry = by_param.get(row.param)
        record = {
            "value": row.value, "source": row.source, "trust": row.trust,
            "captured_at": row.captured_at.isoformat(),
        }
        if entry is None:
            spec = PARAMS.get(row.param)
            by_param[row.param] = {
                "param": row.param, "name": spec.name, "unit": spec.unit,
                **record, "superseded": [],
            }
        else:
            entry["superseded"].append(record)

    return sorted(by_param.values(), key=lambda e: int(e["param"][1:]))


@router.get("/{opportunity_id}/time-in-stage")
def get_time_in_stage(
    opportunity_id: str, db: Session = Depends(get_db), actor: Actor = Depends(current_actor)
) -> dict:
    opp = _get_or_404(db, opportunity_id, actor)
    delta = time_in_current_stage(db, opp)
    return {"opportunity_id": opportunity_id, "stage": opp.stage, "days_in_stage": delta.total_seconds() / 86400}
