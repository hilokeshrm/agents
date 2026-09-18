"""
actual: what shipped (A1/A2, WBS 6.5, 11.4, 11.5). ERP shipped revenue is the
primary actual (decision #69); distributor POS units are the cross-check. Each
row names its source and the connector pull that wrote it, so forecast error
(C15) compares a forecast vintage against a specific, provenanced actual.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Actual(Base):
    __tablename__ = "actual"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    opportunity_id: Mapped[str | None] = mapped_column(ForeignKey("opportunity.id"), nullable=True, index=True)
    part_number: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    region: Mapped[str | None] = mapped_column(String(64), nullable=True)
    customer: Mapped[str | None] = mapped_column(String(128), nullable=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    quarter: Mapped[int] = mapped_column(Integer, nullable=False)

    source: Mapped[str] = mapped_column(String(16), nullable=False)          # "erp" | "pos"
    units_kpcs: Mapped[float | None] = mapped_column(Float, nullable=True)   # A2
    revenue_k: Mapped[float | None] = mapped_column(Float, nullable=True)    # A1
    invoiced_asp: Mapped[float | None] = mapped_column(Float, nullable=True)

    pulled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    pull_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)  # file name / batch id
