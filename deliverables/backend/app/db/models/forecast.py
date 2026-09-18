"""
forecast: quarterly units and revenue phasing (WBS 5.4 NRE recognition, 5.5 the
quarterly phasing rule). Feeds T1 and T2. The phasing rule itself (flat / ramp from
M/P date / programme-driven) is still undecided (WBS 5.5, blocked); this table's
shape does not depend on that choice, only the values written into `phasing_rule`.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Forecast(Base):
    __tablename__ = "forecast"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunity.id"), nullable=False, index=True)
    snapshot_id: Mapped[str | None] = mapped_column(ForeignKey("snapshot.id"), nullable=True, index=True)

    year: Mapped[int] = mapped_column(Integer, nullable=False)
    quarter: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-4

    units_kpcs: Mapped[float] = mapped_column(Float, nullable=False)
    volume_revenue_k: Mapped[float] = mapped_column(Float, nullable=False)
    nre_revenue_k: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)  # WBS 3.5 / 5.4
    phasing_rule: Mapped[str] = mapped_column(String(32), nullable=False)  # "flat" | "ramp" | "programme" -- WBS 5.5

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    opportunity: Mapped["Opportunity"] = relationship(back_populates="forecasts")
