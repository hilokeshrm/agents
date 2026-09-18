"""
target: Finance's top-down commitment by region and period (G1/G2, WBS 6.4,
decision #67). Sheet1's Projection/Stretch block was a template leftover, not a
target; nothing here is seeded from it. Coverage (C13) is dark until Finance
enters rows, and says so.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Target(Base):
    __tablename__ = "target"
    __table_args__ = (UniqueConstraint("region", "period", name="uq_target_region_period"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    region: Mapped[str] = mapped_column(String(64), nullable=False)      # canonical region, or "*" for company
    period: Mapped[str] = mapped_column(String(16), nullable=False)      # "2026", "2026-Q1"
    amount_k: Mapped[float] = mapped_column(Float, nullable=False)       # USD thousands, weighted pipeline expected
    entered_by: Mapped[str] = mapped_column(String(128), nullable=False)
    entered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
