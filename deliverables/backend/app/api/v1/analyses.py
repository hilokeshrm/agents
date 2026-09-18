"""
Analyses, targets, actuals, sweeps and notifications (WBS 6.1-6.6, 8.5, 11.7).

Analyses are read-only reports over the calc engine's figures; the run output
lists what ran and what is dark and which parameter it waits on. Targets are
Finance's (G1/G2, decision #67); actuals are the connectors' (A1/A2) and are
listed here, never entered by hand.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.registry import build_context, discover, run_all
from app.db.models.actual import Actual
from app.db.models.notification import Notification
from app.db.models.target import Target
from app.db.session import get_db
from app.registry.enums import canonicalize_region
from app.security.roles import Actor, current_actor, require

router = APIRouter(tags=["analyses"])


class AnalysisRead(BaseModel):
    key: str
    label: str
    status: str
    headline: str
    figures: dict
    rows: list[dict]
    missing: list[str]
    note: str


class AnalysesRead(BaseModel):
    as_of: str
    scorable_rows: int
    excluded_rows: int
    available_parameters: list[str]
    ran: list[AnalysisRead]
    dark: list[AnalysisRead]


@router.get("/analyses", response_model=AnalysesRead)
def analyses(db: Session = Depends(get_db), actor: Actor = Depends(current_actor)) -> AnalysesRead:
    ctx = build_context(db, actor=actor)
    result = run_all(ctx)
    return AnalysesRead(
        as_of=ctx.as_of.isoformat(), scorable_rows=len(ctx.financials), excluded_rows=ctx.excluded_count,
        available_parameters=sorted(ctx.available),
        ran=[AnalysisRead(**vars(r)) for r in result["ran"].values()],
        dark=[AnalysisRead(**vars(r)) for r in result["dark"].values()],
    )


@router.get("/analyses/catalogue")
def catalogue() -> list[dict]:
    return [{"key": a.key, "label": a.label, "requires": sorted(a.requires), "description": a.description}
            for a in discover().values()]


# --------------------------------------------------------------------------- #
# Targets (G1/G2) -- Finance's
# --------------------------------------------------------------------------- #

class TargetCreate(BaseModel):
    region: str = Field(description='canonical region, or "*" for the company total')
    period: str = Field(pattern=r"^\d{4}(-Q[1-4])?$")
    amount_k: float = Field(gt=0)


class TargetRead(TargetCreate):
    id: str
    entered_by: str
    entered_at: str


def _target_read(t: Target) -> TargetRead:
    return TargetRead(id=t.id, region=t.region, period=t.period, amount_k=t.amount_k,
                      entered_by=t.entered_by, entered_at=t.entered_at.isoformat())


@router.get("/targets", response_model=list[TargetRead])
def list_targets(db: Session = Depends(get_db)) -> list[TargetRead]:
    return [_target_read(t) for t in db.scalars(select(Target).order_by(Target.region, Target.period)).all()]


@router.put("/targets", response_model=TargetRead)
def set_target(payload: TargetCreate, db: Session = Depends(get_db),
               actor: Actor = Depends(current_actor)) -> TargetRead:
    """Finance owns the forecast and its targets (decisions #2, #67); only the
    finance role, or an admin doing provisioning-style setup, may write one."""
    if actor.role not in ("finance", "admin"):
        raise HTTPException(status_code=403, detail="targets are Finance's to enter")
    region = "*" if payload.region.strip() == "*" else canonicalize_region(payload.region)
    if region is None:
        raise HTTPException(status_code=400, detail=f"region {payload.region!r} is on nobody's list")
    existing = db.scalar(select(Target).where(Target.region == region, Target.period == payload.period))
    if existing is not None:
        existing.amount_k, existing.entered_by = payload.amount_k, actor.user_id
        target = existing
    else:
        target = Target(region=region, period=payload.period, amount_k=payload.amount_k, entered_by=actor.user_id)
        db.add(target)
    db.commit()
    db.refresh(target)
    return _target_read(target)


# --------------------------------------------------------------------------- #
# Actuals (A1/A2) -- the connectors'
# --------------------------------------------------------------------------- #

class ActualRead(BaseModel):
    id: str
    part_number: str
    region: str | None
    customer: str | None
    year: int
    quarter: int
    source: str
    units_kpcs: float | None
    revenue_k: float | None
    invoiced_asp: float | None
    pull_ref: str | None


@router.get("/actuals", response_model=list[ActualRead])
def list_actuals(db: Session = Depends(get_db), actor: Actor = Depends(require("pull_forecast_feed"))) -> list[ActualRead]:
    rows = db.scalars(select(Actual).order_by(Actual.year, Actual.quarter, Actual.part_number)).all()
    return [ActualRead(**{k: getattr(a, k) for k in ActualRead.model_fields}) for a in rows]


# --------------------------------------------------------------------------- #
# Sweeps and notifications
# --------------------------------------------------------------------------- #

class SweepRead(BaseModel):
    stalls: int
    overdue_milestones: int
    notifications: int
    findings: int
    review_pending_notices: int


@router.post("/sweeps/nightly", response_model=SweepRead)
def run_nightly_sweep(db: Session = Depends(get_db), actor: Actor = Depends(require("trigger_run")),
                      as_of: date | None = None) -> SweepRead:
    from app.services.notifications import notify_review_pending, sweep

    result = sweep(db, as_of=as_of)
    pending = notify_review_pending(db, as_of=as_of)
    db.commit()
    return SweepRead(**vars(result), review_pending_notices=pending)


class NotificationRead(BaseModel):
    id: str
    kind: str
    recipient: str
    subject: str
    body: str
    status: str
    channel: str | None
    error: str | None
    created_at: str
    sent_at: str | None


@router.get("/notifications", response_model=list[NotificationRead])
def list_notifications(status: str | None = None, db: Session = Depends(get_db),
                       actor: Actor = Depends(current_actor)) -> list[NotificationRead]:
    stmt = select(Notification).order_by(Notification.created_at.desc()).limit(500)
    if status:
        stmt = stmt.where(Notification.status == status)
    rows = db.scalars(stmt).all()
    mine = [n for n in rows if actor.role == "admin" or n.recipient == actor.user_id
            or (n.recipient.startswith("role:") and n.recipient.split(":")[1] == actor.role
                and (actor.sees_all_regions or n.recipient.split(":")[2] in actor.regions))]
    return [NotificationRead(id=n.id, kind=n.kind, recipient=n.recipient, subject=n.subject, body=n.body,
                             status=n.status, channel=n.channel, error=n.error,
                             created_at=n.created_at.isoformat(), sent_at=n.sent_at.isoformat() if n.sent_at else None)
            for n in mine]


class JobRead(BaseModel):
    name: str
    cadence: str
    cron: str


@router.get("/jobs", response_model=list[JobRead])
def list_jobs() -> list[JobRead]:
    from app.services.scheduler import JOBS

    return [JobRead(name=j.name, cadence=j.cadence, cron=j.cron) for j in JOBS.values()]


@router.post("/jobs/{name}/run")
def run_scheduled_job(name: str, db: Session = Depends(get_db), actor: Actor = Depends(require("trigger_run"))) -> dict:
    from app.services.metrics import incr
    from app.services.scheduler import JOBS

    if name not in JOBS:
        raise HTTPException(status_code=404, detail=f"unknown job; jobs are {list(JOBS)}")
    # Same function the scheduler runs, on the request's session.
    try:
        result = JOBS[name].run(db)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        incr(f"job:{name}:failed", 1)
        raise HTTPException(status_code=500, detail=f"{name} failed: {type(exc).__name__}: {exc}") from exc
    incr(f"job:{name}:ok", 1)
    return {"job": name, "ok": True, "result": result}


@router.get("/metrics")
def metrics(actor: Actor = Depends(current_actor)) -> dict:
    from app.services.metrics import month_snapshot

    return month_snapshot()


@router.get("/metrics/prometheus")
def metrics_prometheus():
    from fastapi.responses import PlainTextResponse

    from app.services.metrics import prometheus_text

    return PlainTextResponse(prometheus_text())


@router.post("/notifications/dispatch")
def dispatch(db: Session = Depends(get_db), actor: Actor = Depends(require("trigger_run"))) -> dict:
    from app.services.notifications import dispatch_pending

    result = dispatch_pending(db)
    db.commit()
    return result
