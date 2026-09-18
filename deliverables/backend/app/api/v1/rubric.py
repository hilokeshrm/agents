"""
Rubric & Matrix A admin (WBS 10.7, over 2.3/7.1).

Publishing is the only write. There is no "save settings" here and no editing of
a published version, because the whole value of the table is that a proposal can
name the version that produced it and that version can still be read back
unchanged. A draft lives in the client until it is published.

The impact preview is deliberately narrow about what it claims. It does not
re-run the judgment layer -- publishing re-runs nothing, and pretending to
forecast what a model would say next month would be inventing the answer. What
it does report is deterministic and checkable: which live rows land on a pairing
the draft marks forbidden, and which sit off the draft's baseline, with the
weighted revenue those baselines imply.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.services.financials import adjusted_revenue_k
from app.db.models.opportunity import Opportunity
from app.db.models.proposal import Proposal
from app.db.models.rubric_version import RubricVersion
from app.db.session import get_db
from app.security.roles import Actor, current_actor, require, scope_opportunities
from app.services.rubric_versions import (
    cell_key,
    current_version,
    list_versions,
    matrix_a_template,
    publish,
    publish_v1,
    rubric_template,
)

router = APIRouter(prefix="/rubric", tags=["rubric"])


class RubricVersionRead(BaseModel):
    id: str
    label: str
    matrix_a: dict
    rubric_factors: dict
    published_at: str
    published_by: str
    is_current: bool
    proposal_count: int


class RubricVersionCreate(BaseModel):
    label: str
    matrix_a: dict
    rubric_factors: dict


class DraftRead(BaseModel):
    """What the editor opens with: the current published version if there is
    one, otherwise an empty grid. Never a pre-filled grid of invented baselines
    -- an unset cell reads as unset (WBS 1.1 Q1 is still open)."""

    based_on_version_id: str | None
    based_on_label: str | None
    matrix_a: dict
    rubric_factors: dict


class ImpactRow(BaseModel):
    opportunity_id: str
    project: str
    region: str
    design_status: str
    stage: str
    entered_confidence: float
    baseline: float | None
    delta_pp: float | None
    forbidden: bool
    adjusted_revenue_k: float
    at_baseline_revenue_k: float | None


class ImpactRead(BaseModel):
    rows_considered: int
    rows_forbidden: int
    rows_off_baseline: int
    rows_unset_cell: int
    current_weighted_k: float
    at_baseline_weighted_k: float
    delta_k: float
    rows: list[ImpactRow]


def _read(version: RubricVersion, current_id: str | None, counts: dict[str, int]) -> RubricVersionRead:
    return RubricVersionRead(
        id=version.id, label=version.label, matrix_a=version.matrix_a,
        rubric_factors=version.rubric_factors,
        published_at=version.published_at.isoformat(), published_by=version.published_by,
        is_current=version.id == current_id,
        proposal_count=counts.get(version.id, 0),
    )


def _proposal_counts(db: Session) -> dict[str, int]:
    counts: dict[str, int] = {}
    for (version_id,) in db.execute(select(Proposal.rubric_version_id)).all():
        counts[version_id] = counts.get(version_id, 0) + 1
    return counts


@router.get("/versions", response_model=list[RubricVersionRead])
def get_versions(db: Session = Depends(get_db)) -> list[RubricVersionRead]:
    current = current_version(db)
    counts = _proposal_counts(db)
    return [_read(v, current.id if current else None, counts) for v in list_versions(db)]


@router.get("/draft", response_model=DraftRead)
def get_draft(db: Session = Depends(get_db)) -> DraftRead:
    current = current_version(db)
    if current is None:
        return DraftRead(
            based_on_version_id=None, based_on_label=None,
            matrix_a=matrix_a_template(), rubric_factors=rubric_template(),
        )
    # Carry forward the published grid, but re-derive the axes so a canonical
    # status or stage added since that version appears as a new unset cell
    # rather than silently missing from the editor.
    template = matrix_a_template()
    template["cells"].update(current.matrix_a.get("cells", {}))
    return DraftRead(
        based_on_version_id=current.id, based_on_label=current.label,
        matrix_a=template, rubric_factors=current.rubric_factors,
    )


@router.post("/versions", response_model=RubricVersionRead, status_code=201)
def publish_version(
    payload: RubricVersionCreate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require("publish_rubric")),
) -> RubricVersionRead:
    if not payload.label.strip():
        raise HTTPException(status_code=400, detail="a version needs a label -- it is how a proposal cites it")
    if db.scalars(select(RubricVersion).where(RubricVersion.label == payload.label.strip())).first():
        raise HTTPException(status_code=409, detail=f"version {payload.label!r} already exists; labels are the citation")

    version = publish(
        db, label=payload.label.strip(), matrix_a=payload.matrix_a,
        rubric_factors=payload.rubric_factors, published_by=actor.user_id,
    )
    db.commit()
    db.refresh(version)
    return _read(version, version.id, _proposal_counts(db))


@router.post("/publish-v1", response_model=RubricVersionRead, status_code=201)
def publish_v1_version(
    db: Session = Depends(get_db),
    actor: Actor = Depends(require("publish_rubric")),
) -> RubricVersionRead:
    """Publishes the decision register's v1 rubric as-is: Matrix A baselines,
    Matrix B caps, the 0.05-0.95 bounds, a 20pp run cap, lifecycle bands and
    the gate_all review policy. Idempotent -- a second call returns the
    existing 2026.1 rather than a duplicate."""
    version = publish_v1(db, published_by=actor.user_id)
    db.commit()
    db.refresh(version)
    return _read(version, current_version(db).id, _proposal_counts(db))


class FactorFeedbackRead(BaseModel):
    rule_id: str
    label: str
    fired: int          # times the factor fired on a proposal
    rejected: int       # times a reviewer rejected a proposal citing it (or rejected outright)
    overridden: int     # times a reviewer overrode a proposal it had fired on
    rejection_rate: float | None


class FeedbackRead(BaseModel):
    proposals: int
    rejections: int
    overrides: int
    by_factor: list[FactorFeedbackRead]


@router.get("/feedback", response_model=FeedbackRead)
def factor_feedback(db: Session = Depends(get_db), actor: Actor = Depends(current_actor)) -> FeedbackRead:
    """WBS 8.7: rejections aggregated per rubric factor. A factor rejected
    repeatedly is the earliest signal the rubric is miscalibrated -- it arrives
    months before any won/lost outcome. Reads the append-only confidence_event
    stream; nothing here is stored separately, so it cannot drift from it."""
    from app.db.models.confidence_event import ConfidenceEvent
    from app.judgment.matrix_b import RULES

    # Counts per rule carry no pipeline data -- no customer, no figure, no
    # region -- so this is not region-scoped: it is the rubric admin's screen,
    # and admin sees no pipeline rows by design.
    proposals = list(db.scalars(select(Proposal)).all())
    visible = {p.id for p in proposals}
    fired: dict[str, int] = {r.id: 0 for r in RULES}
    for p in proposals:
        for f in p.factors or []:
            if f.get("applies") and f.get("accepted") and f.get("rule_id") in fired:
                fired[f["rule_id"]] += 1

    rejected: dict[str, int] = {r.id: 0 for r in RULES}
    overridden: dict[str, int] = {r.id: 0 for r in RULES}
    rejections = overrides = 0
    events = db.scalars(select(ConfidenceEvent).where(
        ConfidenceEvent.event_type.in_(("rejection", "override"))
    )).all()
    for e in events:
        if e.proposal_id not in visible:
            continue
        ids = (e.details or {}).get("rejected_factors") or []
        if e.event_type == "rejection":
            rejections += 1
            for i in ids:
                if i in rejected:
                    rejected[i] += 1
        else:
            overrides += 1
            for i in ids:
                if i in overridden:
                    overridden[i] += 1

    return FeedbackRead(
        proposals=len(proposals), rejections=rejections, overrides=overrides,
        by_factor=[
            FactorFeedbackRead(
                rule_id=r.id, label=r.label, fired=fired[r.id], rejected=rejected[r.id],
                overridden=overridden[r.id],
                rejection_rate=(rejected[r.id] / fired[r.id]) if fired[r.id] else None,
            )
            for r in RULES
        ],
    )


@router.post("/impact", response_model=ImpactRead)
def draft_impact(
    payload: RubricVersionCreate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
) -> ImpactRead:
    """What this draft asserts about today's pipeline. Deterministic: no model
    call, no proposal, nothing written."""
    cells = payload.matrix_a.get("cells", {})
    rows = db.scalars(scope_opportunities(select(Opportunity), Opportunity, actor)).all()

    out: list[ImpactRow] = []
    current_total = at_baseline_total = 0.0
    forbidden = off_baseline = unset = 0

    for opp in rows:
        cell = cells.get(cell_key(opp.design_status, opp.stage)) or {}
        baseline = cell.get("baseline")
        is_forbidden = cell.get("allowed") is False

        current_k = adjusted_revenue_k(opp)
        current_total += current_k

        if baseline is None:
            unset += 1
            at_baseline_k = None
            at_baseline_total += current_k  # an unset cell asserts nothing, so it moves nothing
            delta_pp = None
        else:
            at_baseline_k = adjusted_revenue_k(opp, baseline)
            at_baseline_total += at_baseline_k
            delta_pp = (opp.confidence - baseline) * 100
            if abs(delta_pp) > 0.001:
                off_baseline += 1

        if is_forbidden:
            forbidden += 1

        out.append(ImpactRow(
            opportunity_id=opp.id, project=opp.project, region=opp.region,
            design_status=opp.design_status, stage=opp.stage,
            entered_confidence=opp.confidence, baseline=baseline, delta_pp=delta_pp,
            forbidden=is_forbidden, adjusted_revenue_k=current_k, at_baseline_revenue_k=at_baseline_k,
        ))

    out.sort(key=lambda r: (not r.forbidden, -abs(r.delta_pp or 0)))
    return ImpactRead(
        rows_considered=len(out), rows_forbidden=forbidden, rows_off_baseline=off_baseline,
        rows_unset_cell=unset, current_weighted_k=current_total,
        at_baseline_weighted_k=at_baseline_total, delta_k=at_baseline_total - current_total,
        rows=out,
    )
