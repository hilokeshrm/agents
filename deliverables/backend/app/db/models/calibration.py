"""
calibration: owner and region bias from resolved outcomes (WBS J-06, L5 memory) --
a quarterly batch job over state_history's won/lost/M-P outcomes, never a current
number, only ever a prior the judgment layer can cite (submitter_calibration factor
in app/judgment/rubric.py).
"""

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Calibration(Base):
    __tablename__ = "calibration"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)

    owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    region: Mapped[str | None] = mapped_column(String(64), nullable=True)

    bias_pp: Mapped[float] = mapped_column(Float, nullable=False)  # percentage-point bias vs. resolved outcomes
    sd_pp: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)  # J-06 fires beyond one sd
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    # Decision #70: two quarters of history before the prior is treated as reliable.
    reliable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    window_start: Mapped[date] = mapped_column(Date, nullable=False)
    window_end: Mapped[date] = mapped_column(Date, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
