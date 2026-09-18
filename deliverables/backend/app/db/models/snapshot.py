"""
snapshot: write-once record of one run's input -- sha256 of the source, source URI,
row count per tab, timestamp (WBS 3.2). Immutable once sealed, seven-year retention
(WBS 9.7). A run is a pure function of a snapshot: the same input reproduces the
same numbers and the same proposals.
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


class Snapshot(Base):
    __tablename__ = "snapshot"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)

    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_uri: Mapped[str] = mapped_column(String, nullable=False)
    row_counts: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)  # per tab

    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    sealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
