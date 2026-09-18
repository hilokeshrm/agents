"""
Webhook delivery (WBS 10.13). `deliver_event` records one delivery row per
matching subscription and posts it; `retry_failed` re-posts what failed. The
transport is injectable so tests, and a dry run, never touch the network.
"""

import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.webhook import WebhookDelivery, WebhookSubscription

EVENTS = (
    "proposal.raised", "proposal.resolved", "transition.recorded", "run.completed",
    "notification.stall", "notification.milestone", "notification.review_pending",
    "notification.transition_proposed", "notification.reconciliation", "connector.pulled",
)


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _post(url: str, body: bytes, headers: dict) -> int:
    import requests

    return requests.post(url, data=body, headers=headers, timeout=10).status_code


_transport: Callable[[str, bytes, dict], int] = _post


def set_transport(fn: Callable[[str, bytes, dict], int] | None) -> None:
    global _transport
    _transport = fn or _post


def _matches(sub: WebhookSubscription, event: str) -> bool:
    return any(e == "*" or e == event or (e.endswith(".*") and event.startswith(e[:-1])) for e in (sub.events or []))


def deliver_event(db: Session, *, event: str, payload: dict) -> list[WebhookDelivery]:
    subs = [s for s in db.scalars(select(WebhookSubscription).where(WebhookSubscription.active.is_(True))).all()
            if _matches(s, event)]
    deliveries = []
    for sub in subs:
        d = WebhookDelivery(subscription_id=sub.id, event=event, payload=payload)
        db.add(d)
        db.flush()
        _attempt(sub, d)
        deliveries.append(d)
    db.flush()
    return deliveries


def _attempt(sub: WebhookSubscription, d: WebhookDelivery) -> None:
    body = json.dumps({"event": d.event, "delivery_id": d.id, "sent_at": datetime.now(timezone.utc).isoformat(),
                       "payload": d.payload}, default=str).encode()
    headers = {"Content-Type": "application/json", "X-OppTrack-Event": d.event,
               "X-OppTrack-Signature": sign(sub.secret, body), "X-OppTrack-Delivery": d.id}
    d.attempts += 1
    try:
        code = _transport(sub.url, body, headers)
        d.response_code = code
        if 200 <= code < 300:
            d.status, d.error, d.sent_at = "sent", None, datetime.now(timezone.utc)
        else:
            d.status, d.error = "failed", f"HTTP {code}"
    except Exception as exc:  # noqa: BLE001 -- recorded on the row
        d.status, d.error = "failed", f"{type(exc).__name__}: {exc}"


def retry_failed(db: Session, *, max_attempts: int = 5) -> int:
    rows = db.scalars(select(WebhookDelivery).where(WebhookDelivery.status == "failed",
                                                    WebhookDelivery.attempts < max_attempts)).all()
    subs = {s.id: s for s in db.scalars(select(WebhookSubscription)).all()}
    for d in rows:
        _attempt(subs[d.subscription_id], d)
    db.flush()
    return len(rows)
