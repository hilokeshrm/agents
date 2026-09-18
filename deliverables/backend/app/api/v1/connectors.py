"""
Connector pulls and the reconciliation queue (WBS 11.1-11.6).

A pull is a file upload today (the connectors read a CSV/JSON export); the
same handler runs on the scheduler against a drop folder. `dry_run=true`
records what the pull would have changed without writing a row -- the
fortnight-of-watching the framework's docstring describes.
"""

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors import CONNECTORS, catalogue
from app.connectors._framework import apply_observations
from app.db.models.opportunity import Opportunity
from app.db.models.proposal import Proposal
from app.db.session import get_db
from app.security.roles import Actor, current_actor, scope_opportunities

router = APIRouter(prefix="/connectors", tags=["connectors"])


class PullRead(BaseModel):
    connector: str
    ref: str
    dry_run: bool
    observations: int
    matched: int
    unmatched: int
    applied: int
    reconciliation_items: int
    unchanged: int
    actuals_loaded: int = 0
    programmes_loaded: int = 0
    details: list[dict]


def _may_pull(actor: Actor, name: str) -> None:
    if actor.role == "admin":
        return
    if actor.role == "service":
        # A service account is scoped to one connector (app/api/v1/users.py).
        return
    raise HTTPException(status_code=403, detail="pulls are for the connector's service account or an admin")


@router.get("")
def list_connectors() -> list[dict]:
    return catalogue()


@router.post("/{name}/pull", response_model=PullRead)
async def pull(
    name: str,
    file: UploadFile = File(...),
    dry_run: bool = Form(default=False),
    db: Session = Depends(get_db),
    actor: Actor = Depends(current_actor),
) -> PullRead:
    connector = CONNECTORS.get(name)
    if connector is None:
        raise HTTPException(status_code=404, detail=f"no connector {name!r}; see GET /connectors")
    _may_pull(actor, name)
    content = await file.read()
    ref = f"{name}:{file.filename or 'upload'}"
    actuals = programmes = 0
    try:
        if name in ("erp", "disty_pos") and not dry_run:
            actuals = connector.load_actuals(db, content, ref=ref)
        if name == "market_data" and not dry_run:
            programmes = connector.load(db, content, ref=ref)
        observations = (connector.observations(db, content, ref=ref) if name == "erp"
                        else connector.pull(content, ref=ref))
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=f"{name} extract could not be read: {exc}") from exc
    result = apply_observations(db, connector.spec, observations, actor=actor.user_id, ref=ref, dry_run=dry_run)
    if dry_run:
        db.rollback()
    else:
        db.commit()
    return PullRead(**vars(result), actuals_loaded=actuals, programmes_loaded=programmes)


class ReconciliationRead(BaseModel):
    id: str
    opportunity_id: str
    project: str
    region: str
    field: str
    current_value: object
    observed_value: object
    source: str
    trust: int
    current_trust: int
    gated: bool
    reason: str
    ref: str
    status: str


@router.get("/reconciliation", response_model=list[ReconciliationRead])
def reconciliation_queue(db: Session = Depends(get_db), actor: Actor = Depends(current_actor)) -> list[ReconciliationRead]:
    stmt = (select(Proposal, Opportunity).join(Opportunity, Proposal.opportunity_id == Opportunity.id)
            .where(Proposal.kind == "reconciliation", Proposal.status == "pending").order_by(Proposal.created_at))
    out = []
    for p, o in db.execute(scope_opportunities(stmt, Opportunity, actor)).all():
        t = p.transition or {}
        out.append(ReconciliationRead(
            id=p.id, opportunity_id=o.id, project=o.project, region=o.region, field=t.get("field"),
            current_value=t.get("current_value"), observed_value=t.get("observed_value"), source=t.get("source"),
            trust=t.get("trust"), current_trust=t.get("current_trust"), gated=bool(t.get("gated")),
            reason=t.get("reason", ""), ref=t.get("ref", ""), status=p.status,
        ))
    return out
