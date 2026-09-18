"""
opportunity_sequence: the counter behind the human-readable Opportunity ID
(WBS 2.4, decision #56 -- "OPP-000001").

One row per issued id; the autoincrement primary key is the number. A table
rather than max()+1 so two concurrent intakes cannot mint the same id, and a
table rather than a database sequence so it works identically on SQLite and
Postgres. Rows are never deleted: a gap would be a lie about what was issued.
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class OpportunitySequence(Base):
    __tablename__ = "opportunity_sequence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    issued_to: Mapped[str | None] = mapped_column(String(36), nullable=True)  # opportunity.id, once known
