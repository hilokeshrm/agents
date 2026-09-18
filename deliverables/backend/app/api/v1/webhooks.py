"""
Webhooks and exports (WBS 10.13), and the ROI Agent feed contract (WBS 1.6,
decision #91).

Exports are the same figures the screens show, as CSV or JSON, computed on
request from the calc engine -- never a cached table. The ROI feed is the
agreed hand-off shape: snapshot-linked, versioned, one row per opportunity
and period, with the calculation and rubric versions on every row so the ROI
Agent's independent forecast can be cross-checked against it (decision #3).
"""

import csv
import io
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calc.phasing import phase, quarterly_revenue_k
from app.db.models.confidence_event import ConfidenceEvent
from app.db.models.opportunity import Opportunity
from app.db.models.run import Run
from app.db.models.webhook import WebhookDelivery, WebhookSubscription
from app.db.session import get_db
from app.security.roles import Actor, current_actor, require, scope_opportunities
from app.services.financials import financials_for
from app.services.rubric_versions import current_version
from app.services.webhooks import EVENTS, retry_failed

router = APIRouter(tags=["webhooks"])

CALC_VERSION = "calc-2026.09"   # bumps when app/calc changes a formula; stamped on every feed row


class SubscriptionCreate(BaseModel):
    url: str
    events: list[str] = ["*"]


class SubscriptionRead(BaseModel):
    id: str
    url: str
    events: list[str]
    active: bool
    created_by: str
    created_at: str
    secret: str | None = None   # returned once, at creation


@router.get("/webhooks/events")
def list_events() -> list[str]:
    return list(EVENTS)


@router.get("/webhooks", response_model=list[SubscriptionRead])
def list_subscriptions(db: Session = Depends(get_db), actor: Actor = Depends(require("provision_users"))) -> list[SubscriptionRead]:
    return [SubscriptionRead(id=s.id, url=s.url, events=s.events, active=s.active, created_by=s.created_by,
                             created_at=s.created_at.isoformat())
            for s in db.scalars(select(WebhookSubscription).order_by(WebhookSubscription.created_at)).all()]


@router.post("/webhooks", response_model=SubscriptionRead, status_code=201)
def subscribe(payload: SubscriptionCreate, db: Session = Depends(get_db),
              actor: Actor = Depends(require("provision_users"))) -> SubscriptionRead:
    if not payload.url.startswith(("https://", "http://")):
        raise HTTPException(status_code=400, detail="url must be http(s)")
    unknown = [e for e in payload.events if e != "*" and not e.endswith(".*") and e not in EVENTS]
    if unknown:
        raise HTTPException(status_code=400, detail=f"unknown events {unknown}; see GET /webhooks/events")
    sub = WebhookSubscription(url=payload.url, events=payload.events, secret=secrets.token_urlsafe(32),
                              created_by=actor.user_id)
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return SubscriptionRead(id=sub.id, url=sub.url, events=sub.events, active=sub.active, created_by=sub.created_by,
                            created_at=sub.created_at.isoformat(), secret=sub.secret)


@router.delete("/webhooks/{subscription_id}", status_code=204)
def unsubscribe(subscription_id: str, db: Session = Depends(get_db), actor: Actor = Depends(require("provision_users"))):
    sub = db.get(WebhookSubscription, subscription_id)
    if sub is None:
        raise HTTPException(status_code=404, detail="subscription not found")
    sub.active = False
    db.commit()
    return Response(status_code=204)


@router.get("/webhooks/deliveries")
def deliveries(status: str | None = None, db: Session = Depends(get_db),
               actor: Actor = Depends(require("provision_users"))) -> list[dict]:
    stmt = select(WebhookDelivery).order_by(WebhookDelivery.created_at.desc()).limit(200)
    if status:
        stmt = stmt.where(WebhookDelivery.status == status)
    return [{"id": d.id, "subscription_id": d.subscription_id, "event": d.event, "status": d.status,
             "attempts": d.attempts, "response_code": d.response_code, "error": d.error,
             "created_at": d.created_at.isoformat()} for d in db.scalars(stmt).all()]


@router.post("/webhooks/retry")
def retry(db: Session = Depends(get_db), actor: Actor = Depends(require("provision_users"))) -> dict:
    n = retry_failed(db)
    db.commit()
    return {"retried": n}


# --------------------------------------------------------------------------- #
# Exports
# --------------------------------------------------------------------------- #

def _csv(rows: list[dict], filename: str) -> Response:
    buf = io.StringIO()
    if rows:
        writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return Response(content=buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def _opportunity_rows(db: Session, actor: Actor) -> list[dict]:
    rows = []
    for o in db.scalars(scope_opportunities(select(Opportunity), Opportunity, actor).order_by(Opportunity.created_at)).all():
        f = financials_for(o)
        rows.append({
            "external_id": o.external_id, "region": o.region, "customer": o.customer, "end_customer": o.end_customer,
            "project": o.project, "application": o.application, "product_line": o.product_line,
            "part_number": o.part_number, "design_status": o.design_status, "stage": o.stage,
            "mp_date": o.mp_date.isoformat() if o.mp_date else "", "eau_kpcs": o.eau_kpcs, "unit_set": o.unit_set,
            "disty_asp": o.disty_asp, "resale_asp": o.resale_asp, "confidence": o.confidence,
            "sales_revenue_k": f.sales_revenue_k, "adjusted_revenue_k": f.adjusted_revenue_k,
            "nre_revenue_k": f.nre_revenue_k, "owner": o.owner, "competitor_part": o.competitor_part,
        })
    return rows


@router.get("/exports/opportunities.csv")
def export_opportunities(db: Session = Depends(get_db), actor: Actor = Depends(current_actor)) -> Response:
    return _csv(_opportunity_rows(db, actor), "opportunities.csv")


@router.get("/exports/audit.csv")
def export_audit(db: Session = Depends(get_db), actor: Actor = Depends(require("pull_forecast_feed"))) -> Response:
    visible = {o.id: o for o in db.scalars(scope_opportunities(select(Opportunity), Opportunity, actor)).all()}
    rows = []
    for e in db.scalars(select(ConfidenceEvent).order_by(ConfidenceEvent.occurred_at)).all():
        if e.opportunity_id not in visible:
            continue
        rows.append({"occurred_at": e.occurred_at.isoformat(), "external_id": visible[e.opportunity_id].external_id,
                     "event_type": e.event_type, "base_confidence": e.base_confidence,
                     "resulting_confidence": e.resulting_confidence, "actor": e.actor, "actor_role": e.actor_role,
                     "reason_code": e.reason_code, "model_id": e.model_id, "prompt_version": e.prompt_version,
                     "rubric_version_id": e.rubric_version_id, "note": e.note})
    return _csv(rows, "audit.csv")


def roi_feed(db: Session, actor: Actor) -> dict:
    """Decision #91: snapshot id, opportunity id, external id, region, customer,
    product line, part, period, sales revenue, adjusted revenue, confidence,
    status, stage, source, calculation version, rubric version."""
    version = current_version(db)
    last_run = db.scalars(select(Run).where(Run.status == "completed").order_by(Run.finished_at.desc())).first()
    rows = []
    for o in db.scalars(scope_opportunities(select(Opportunity), Opportunity, actor).order_by(Opportunity.created_at)).all():
        f = financials_for(o)
        profile = {int(k): v for k, v in (o.phasing_profile or {}).items()} or None
        p = phase(eau_kpcs=o.eau_kpcs, mp_date=o.mp_date, profile=profile)
        periods = quarterly_revenue_k(p, f.adjusted_revenue_k) or {None: f.adjusted_revenue_k}
        sales_periods = quarterly_revenue_k(p, f.sales_revenue_k) or {None: f.sales_revenue_k}
        for key, adjusted in periods.items():
            rows.append({
                "snapshot_id": last_run.id if last_run else None,
                "opportunity_id": o.id, "external_id": o.external_id, "region": o.region, "customer": o.customer,
                "product_line": o.product_line, "part_number": o.part_number,
                "period": f"{key[0]}-Q{key[1]}" if key else "unphased",
                "sales_revenue_k": sales_periods[key], "adjusted_revenue_k": adjusted, "confidence": o.confidence,
                "design_status": o.design_status, "stage": o.stage, "source": "opportunity_tracking_agent",
                "calculation_version": CALC_VERSION, "rubric_version": version.label if version else None,
                "phasing_basis": p.basis,
            })
    return {"generated_at": datetime.now(timezone.utc).isoformat(), "contract": "roi-feed-v1",
            "calculation_version": CALC_VERSION, "rubric_version": version.label if version else None,
            "rows": rows}


@router.get("/exports/roi-feed.json")
def export_roi_feed(db: Session = Depends(get_db), actor: Actor = Depends(require("pull_forecast_feed"))) -> dict:
    return roi_feed(db, actor)


class ROICrossCheckIn(BaseModel):
    rows: list[dict]   # the ROI Agent's own figures: external_id, period, adjusted_revenue_k


@router.post("/exports/roi-cross-check")
def roi_cross_check(payload: ROICrossCheckIn, db: Session = Depends(get_db),
                    actor: Actor = Depends(require("pull_forecast_feed"))) -> dict:
    """Decision #4: differences between this agent's feed and the ROI Agent's
    independent figure become review findings, not silent reconciliation."""
    ours = {(r["external_id"], r["period"]): r["adjusted_revenue_k"] for r in roi_feed(db, actor)["rows"]}
    findings = []
    for r in payload.rows:
        key = (r.get("external_id"), r.get("period"))
        theirs = float(r.get("adjusted_revenue_k") or 0.0)
        mine = ours.get(key)
        if mine is None:
            findings.append({"external_id": key[0], "period": key[1], "ours": None, "roi": theirs, "kind": "not_in_feed"})
        elif abs(mine - theirs) > max(1.0, 0.05 * abs(mine)):
            findings.append({"external_id": key[0], "period": key[1], "ours": mine, "roi": theirs,
                             "difference_k": theirs - mine, "kind": "differs"})
    return {"compared": len(payload.rows), "findings": findings}
