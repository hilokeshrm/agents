"""
notification: outbound messages (WBS 11.7) -- a stall, an overdue milestone, a
proposal awaiting review, a transition proposed. Written by the sweeps and the
run, delivered by app/services/notifications.dispatch_pending through whatever
channel is configured (log, SMTP, webhook). Delivery state is on the row so a
failed send is visible, not lost.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Notification(Base):
    __tablename__ = "notification"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)          # stall | milestone | review_pending | transition_proposed | reconciliation
    recipient: Mapped[str] = mapped_column(String(128), nullable=False)    # user id, or "role:manager:Korea"
    subject: Mapped[str] = mapped_column(String(256), nullable=False)
    body: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    dedupe_key: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")  # pending | sent | failed
    channel: Mapped[str | None] = mapped_column(String(16), nullable=True)
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
