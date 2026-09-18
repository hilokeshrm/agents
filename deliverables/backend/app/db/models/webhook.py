"""
webhook_subscription and webhook_delivery (WBS 10.13): outbound events to the
Workflow Manager, the ROI Agent or anything else that wants to know a proposal
was raised, a record moved, a run completed or a stall was flagged.

Deliveries are rows, so a failed POST is visible and retried, never lost.
Every request is signed (HMAC-SHA256 over the body with the subscription's
secret) so the receiver can refuse a forgery.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class WebhookSubscription(Base):
    __tablename__ = "webhook_subscription"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    url: Mapped[str] = mapped_column(String(512), nullable=False)
    events: Mapped[list] = mapped_column(JSON, nullable=False, default=list)   # ["proposal.raised", "*"]
    secret: Mapped[str] = mapped_column(String(128), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class WebhookDelivery(Base):
    __tablename__ = "webhook_delivery"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    subscription_id: Mapped[str] = mapped_column(ForeignKey("webhook_subscription.id"), nullable=False, index=True)
    event: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")   # pending | sent | failed
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    response_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
