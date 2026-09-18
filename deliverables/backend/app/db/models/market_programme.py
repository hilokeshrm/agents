"""market_programme: licensed vehicle-programme data (P1/P2, WBS 11.6). Empty
until the data licence exists; the EAU cross-check and white-space analyses
report dark until it has rows."""

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class MarketProgramme(Base):
    __tablename__ = "market_programme"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    programme: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    oem: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    region: Mapped[str | None] = mapped_column(String(64), nullable=True)
    application: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sop: Mapped[date | None] = mapped_column(Date, nullable=True)
    build_volume_ksets: Mapped[float | None] = mapped_column(Float, nullable=True)
    pulled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    pull_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
