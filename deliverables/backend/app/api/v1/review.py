"""
Review console and run endpoints (WBS 10.5, 10.9, and the human gate of 8.1).

Every write here goes through app/services/proposals.py, which is where the
separation-of-duties and reason-code rules live -- this router's job is the HTTP
shape, the region scope, and the role gate, not the decision rules.

Region scope is applied as a query filter (app/security/roles.py), so a manager
scoped to Korea listing the queue does not receive EU proposals and then have
them hidden; the rows never leave the database.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.services.financials import adjusted_revenue_k
from app.db.models.confidence_event import ConfidenceEvent
from app.db.models.finding import Finding
from app.db.models.opportunity import Opportunity
from app.db.models.proposal import Proposal
from app.db.models.rubric_version import RubricVersion
from app.db.models.run import Run
from app.db.models.state_history import StateHistory
from app.db.session import get_db
from app.judgment.rubric import score_confidence_factors
from app.schemas.review import (
    AuditEventRead,
    ProposalRead,
    ProposalResolve,
    RunCreate,
    RunRead,
)
from app.security.roles import Actor, current_actor, require, scope_opportunities
from app.services.judgment_runs import execute_run, single_row_bundle
from app.services.proposals import (
    ProposalError,
    raise_proposal,
    resolve_proposal,
)
from app.services.rubric_versions import baseline_for, current_version

router = APIRouter(tags=["review"])


def _revenue(opp: Opportunity, confidence: float) -> float:
    return adjusted_revenue_k(opp, confidence)


def _actionable(actor: Actor, opp: Opportunity) -> tuple[bool, str | None]:
    """The same three checks the write path enforces, asked ahead of time so the
    screen can explain a disabled control instead of failing on click."""
    if not actor.can_act_on_region("approve_reject_proposal", opp.region):
        grant = actor.grant("approve_reject_proposal")
        if grant == "own_region":
            return False, f"{opp.region} is outside your region scope"
        return False, f"the {actor.role} role has no approve grant"
    if actor.user_id.strip().lower() == (opp.owner or "").strip().lower():
        return False, "you own this row -- a reviewer cannot approve their own number"
    return True, None


def _proposal_read(proposal: Proposal, opp: Opportunity, version: RubricVersion | None, actor: Actor) -> ProposalRead:
    actionable, blocked_reason = _actionable(actor, opp)
    return ProposalRead(
        id=proposal.id,
        opportunity_id=proposal.opportunity_id,
        run_id=proposal.run_id,
        rubric_version_id=proposal.rubric_version_id,
        rubric_version_label=version.label if version else None,
        status=proposal.status,
        base_confidence=proposal.base_confidence,
        proposed_confidence=proposal.proposed_confidence,
        band_crossing=proposal.band_crossing,
        kind=proposal.kind,
        transition=proposal.transition,
        flags=proposal.flags or {},
        factors=proposal.factors,
        created_at=proposal.created_at,
        resolved_at=proposal.resolved_at,
        resolved_by=proposal.resolved_by,
        project=opp.project,
        customer=opp.customer,
        region=opp.region,
        owner=opp.owner,
        design_status=opp.design_status,
        stage=opp.stage,
        part_number=opp.part_number,
        matrix_a_baseline=baseline_for(version, opp.design_status, opp.stage) if version else None,
        base_adjusted_revenue_k=_revenue(opp, proposal.base_confidence),
        proposed_adjusted_revenue_k=_revenue(opp, proposal.proposed_confidence),
        actionable=actionable,
        blocked_reason=blocked_reason,
    )


def _versions_by_id(db: Session) -> dict[str, RubricVersion]:
    return {v.id: v for v in db.scalars(select(RubricVersion)).all()}


# --------------------------------------------------------------------------- #
# Proposals
# --------------------------------------------------------------------------- #

@router.get("/proposals", response_model=list[ProposalRead])
def list_proposals(
    status: str | None = "pending",
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
) -> list[ProposalRead]:
    stmt = (
        select(Proposal, Opportunity)
        .join(Opportunity, Proposal.opportunity_id == Opportunity.id)
        .order_by(Proposal.created_at.desc())
    )
    if status and status != "all":
        stmt = stmt.where(Proposal.status == status)
    stmt = scope_opportunities(stmt, Opportunity, actor)

    versions = _versions_by_id(db)
    return [
        _proposal_read(proposal, opp, versions.get(proposal.rubric_version_id), actor)
        for proposal, opp in db.execute(stmt).all()
    ]


@router.get("/proposals/{proposal_id}", response_model=ProposalRead)
def get_proposal(
    proposal_id: str, db: Session = Depends(get_db), actor: Actor = Depends(current_actor)
) -> ProposalRead:
    proposal, opp = _get_pair_or_404(db, proposal_id, actor)
    return _proposal_read(proposal, opp, db.get(RubricVersion, proposal.rubric_version_id), actor)


def _get_pair_or_404(db: Session, proposal_id: str, actor: Actor) -> tuple[Proposal, Opportunity]:
    stmt = (
        select(Proposal, Opportunity)
        .join(Opportunity, Proposal.opportunity_id == Opportunity.id)
        .where(Proposal.id == proposal_id)
    )
    row = db.execute(scope_opportunities(stmt, Opportunity, actor)).first()
    if row is None:
        # 404 rather than 403 for an out-of-scope row: a 403 would confirm it exists.
        raise HTTPException(status_code=404, detail="Proposal not found")
    return row[0], row[1]


@router.post("/proposals/{proposal_id}/resolve", response_model=ProposalRead)
def resolve(
    proposal_id: str,
    payload: ProposalResolve,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require("approve_reject_proposal")),
) -> ProposalRead:
    proposal, opp = _get_pair_or_404(db, proposal_id, actor)

    action_permission = "override_with_own_value" if payload.action == "override" else "approve_reject_proposal"
    if proposal.kind == "transition" and payload.action == "approve":
        # Approving a lifecycle move is a close: the same grant the manual
        # transition route requires (WBS 8.3 -- the gate is identical either way).
        action_permission = "close_design_lost"
    if proposal.kind == "reconciliation" and payload.action == "approve" and (
        (proposal.transition or {}).get("field") == "design_status"
        and str((proposal.transition or {}).get("observed_value", "")).lower() in ("lost", "mass production")
    ):
        action_permission = "close_design_lost"
    if not actor.can_act_on_region(action_permission, opp.region):
        raise HTTPException(
            status_code=403,
            detail=f"role {actor.role!r} may not {payload.action} in region {opp.region!r} "
                   f"(grant: {actor.grant(action_permission)})",
        )

    try:
        resolve_proposal(
            db, proposal, opp,
            action=payload.action, actor=actor.user_id, actor_role=actor.role,
            value=payload.value, reason_code=payload.reason_code, note=payload.note,
            rejected_factors=payload.rejected_factors,
        )
    except ProposalError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    db.commit()
    db.refresh(proposal)
    db.refresh(opp)
    return _proposal_read(proposal, opp, db.get(RubricVersion, proposal.rubric_version_id), actor)


@router.post("/opportunities/{opportunity_id}/request-review", response_model=ProposalRead, status_code=201)
def request_review(
    opportunity_id: str,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require("request_review")),
) -> ProposalRead:
    """Score one row and queue the result -- the owner-side half of the review
    loop, and the same code path a portfolio run takes for every row."""
    opp = db.get(Opportunity, opportunity_id)
    if opp is None or not actor.in_scope(opp.region):
        raise HTTPException(status_code=404, detail="Opportunity not found")

    version = current_version(db)
    if version is None:
        raise HTTPException(
            status_code=409,
            detail="no published rubric version -- publish one in Rubric & Matrix A first, "
                   "so the proposal can be stamped with the version that produced it",
        )
    if db.scalars(select(Proposal).where(
        Proposal.opportunity_id == opp.id, Proposal.status == "pending"
    )).first() is not None:
        raise HTTPException(status_code=409, detail="this opportunity already has an open proposal")

    bundle = single_row_bundle(db, opp, version)
    result = score_confidence_factors(bundle)
    raised = raise_proposal(
        db, opp, version, result["factors"],
        mode=result["mode"],
        model_id=None if result["mode"] == "mock" else _judgment_model(),
        actor=actor.user_id,
        bundle=bundle,
    )
    db.commit()
    db.refresh(raised.proposal)
    return _proposal_read(raised.proposal, opp, version, actor)


def _judgment_model() -> str:
    from app.core.config import settings

    return settings.judgment_model


# --------------------------------------------------------------------------- #
# Runs
# --------------------------------------------------------------------------- #

def _run_read(run: Run, versions: dict[str, RubricVersion]) -> RunRead:
    version = versions.get(run.rubric_version_id)
    return RunRead(
        id=run.id, kind=run.kind, status=run.status, mode=run.mode,
        rubric_version_id=run.rubric_version_id,
        rubric_version_label=version.label if version else None,
        snapshot_id=run.snapshot_id, actor=run.actor, steps=run.steps, counts=run.counts,
        error=run.error, started_at=run.started_at, finished_at=run.finished_at,
    )


@router.get("/runs", response_model=list[RunRead])
def list_runs(db: Session = Depends(get_db)) -> list[RunRead]:
    versions = _versions_by_id(db)
    runs = db.scalars(select(Run).order_by(Run.started_at.desc())).all()
    return [_run_read(r, versions) for r in runs]


@router.get("/runs/{run_id}", response_model=RunRead)
def get_run(run_id: str, db: Session = Depends(get_db)) -> RunRead:
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return _run_read(run, _versions_by_id(db))


class RowDiffRead(BaseModel):
    opportunity_id: str
    project: str
    a_proposed: float | None
    b_proposed: float | None
    a_rules: list[str]
    b_rules: list[str]
    same: bool
    attributed_to: list[str]


class RunComparisonRead(BaseModel):
    run_a: str
    run_b: str
    stamps_a: dict
    stamps_b: dict
    stamp_differences: list[str]
    rows: list[RowDiffRead]
    identical: bool
    unattributed_differences: int


@router.get("/runs/{run_id}/compare/{other_id}", response_model=RunComparisonRead)
def compare(run_id: str, other_id: str, db: Session = Depends(get_db),
            actor: Actor = Depends(current_actor)) -> RunComparisonRead:
    """WBS 6.6: two runs side by side, every difference attributed to a
    recorded version change or labelled unattributed."""
    from app.services.run_compare import compare_runs

    try:
        result = compare_runs(db, run_id, other_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Run not found")
    return RunComparisonRead(
        run_a=result.run_a, run_b=result.run_b, stamps_a=result.stamps_a, stamps_b=result.stamps_b,
        stamp_differences=result.stamp_differences, rows=[RowDiffRead(**vars(r)) for r in result.rows],
        identical=result.identical, unattributed_differences=result.unattributed_differences,
    )


@router.get("/runs/{run_id}/proposals", response_model=list[ProposalRead])
def run_proposals(
    run_id: str, db: Session = Depends(get_db), actor: Actor = Depends(current_actor)
) -> list[ProposalRead]:
    stmt = (
        select(Proposal, Opportunity)
        .join(Opportunity, Proposal.opportunity_id == Opportunity.id)
        .where(Proposal.run_id == run_id)
        .order_by(Proposal.created_at)
    )
    versions = _versions_by_id(db)
    return [
        _proposal_read(p, o, versions.get(p.rubric_version_id), actor)
        for p, o in db.execute(scope_opportunities(stmt, Opportunity, actor)).all()
    ]


@router.post("/runs", response_model=RunRead, status_code=201)
def trigger_run(
    payload: RunCreate | None = None,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require("trigger_run")),
) -> RunRead:
    version = current_version(db)
    if version is None:
        raise HTTPException(
            status_code=409,
            detail="no published rubric version -- a run must stamp the version that produced its "
                   "proposals, so publishing one is a precondition, not a default",
        )
    run = execute_run(
        db, version=version, actor=actor.user_id,
        opportunity_ids=(payload.opportunity_ids if payload else None),
    )
    db.commit()
    db.refresh(run)
    return _run_read(run, {version.id: version})


# --------------------------------------------------------------------------- #
# Audit feed
# --------------------------------------------------------------------------- #

@router.get("/audit", response_model=list[AuditEventRead])
def audit_feed(
    opportunity_id: str | None = None,
    limit: int = 200,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
) -> list[AuditEventRead]:
    """The append-only stream, assembled from the three tables that actually
    record decisions. Nothing in this codebase updates or deletes a row in any
    of them, which is what makes "nobody can edit an audit entry" a property of
    the schema rather than a promise."""
    projects: dict[str, tuple[str, str]] = {
        opp.id: (opp.project, opp.region)
        for opp in db.scalars(scope_opportunities(select(Opportunity), Opportunity, actor)).all()
    }
    visible = set(projects)
    events: list[AuditEventRead] = []

    conf_stmt = select(ConfidenceEvent).order_by(ConfidenceEvent.occurred_at.desc()).limit(limit)
    if opportunity_id:
        conf_stmt = conf_stmt.where(ConfidenceEvent.opportunity_id == opportunity_id)
    for e in db.scalars(conf_stmt).all():
        if e.opportunity_id not in visible:
            continue
        events.append(AuditEventRead(
            at=e.occurred_at, source="confidence_event", kind=e.event_type,
            opportunity_id=e.opportunity_id, project=projects[e.opportunity_id][0],
            actor=e.actor, actor_role=e.actor_role,
            summary=f"{e.base_confidence:.2f} -> {e.resulting_confidence:.2f}",
            detail=" · ".join(filter(None, [e.note, f"model {e.model_id}" if e.model_id else None])),
            reason_code=e.reason_code, proposal_id=e.proposal_id, run_id=None,
        ))

    state_stmt = select(StateHistory).order_by(StateHistory.occurred_at.desc()).limit(limit)
    if opportunity_id:
        state_stmt = state_stmt.where(StateHistory.opportunity_id == opportunity_id)
    for e in db.scalars(state_stmt).all():
        if e.opportunity_id not in visible:
            continue
        events.append(AuditEventRead(
            at=e.occurred_at, source="state_history", kind=e.field,
            opportunity_id=e.opportunity_id, project=projects[e.opportunity_id][0],
            actor=e.actor, actor_role=None,
            summary=f"{e.from_value or 'created'} -> {e.to_value}",
            detail=None, reason_code=e.reason_code, proposal_id=None, run_id=None,
        ))

    finding_stmt = select(Finding).order_by(Finding.occurred_at.desc()).limit(limit)
    if opportunity_id:
        finding_stmt = finding_stmt.where(Finding.opportunity_id == opportunity_id)
    for f in db.scalars(finding_stmt).all():
        if f.opportunity_id is not None and f.opportunity_id not in visible:
            continue
        events.append(AuditEventRead(
            at=f.occurred_at, source="finding", kind=f.severity,
            opportunity_id=f.opportunity_id,
            project=projects[f.opportunity_id][0] if f.opportunity_id in projects else None,
            actor="intake", actor_role=None, summary=f.rule_id, detail=f.message,
            reason_code=None, proposal_id=None, run_id=None,
        ))

    events.sort(key=lambda e: e.at, reverse=True)
    return events[:limit]
