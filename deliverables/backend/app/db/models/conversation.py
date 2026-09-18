"""conversation: every assistant question and answer (WBS 14.5) -- who asked,
what mode answered, which tools ran, whether the answer was grounded, and the
request id, so a figure quoted in chat can be traced the same way a figure in
a board pack can."""

import threading
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import JSON, Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


_last_stamp: datetime | None = None
_stamp_lock = threading.Lock()


def _now() -> datetime:
    """A strictly increasing timestamp within this process.

    The history endpoint orders conversations by created_at; two questions
    asked within one clock tick (Windows ticks are milliseconds) would
    otherwise share a stamp and come back in undefined order.
    """
    global _last_stamp
    with _stamp_lock:
        stamp = datetime.now(timezone.utc)
        if _last_stamp is not None and stamp <= _last_stamp:
            stamp = _last_stamp + timedelta(microseconds=1)
        _last_stamp = stamp
        return stamp


class Conversation(Base):
    __tablename__ = "conversation"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    actor: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    actor_role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    question: Mapped[str] = mapped_column(String, nullable=False)
    answer: Mapped[str] = mapped_column(String, nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)     # live | reader | refused
    intent: Mapped[str] = mapped_column(String(16), nullable=False)   # answer | refuse_write | refuse_scope
    tool_calls: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    grounded: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    untraceable: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    model_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
