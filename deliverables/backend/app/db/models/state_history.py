"""
state_history: append-only event stream for every Design Status and Stage
transition (WBS 9.2). This is what converts Design Status from a cell that gets
overwritten into the source for stall detection, time-in-stage, velocity, win rate
and the outcome labels the calibration table needs later -- a decision to stop
overwriting, not a data-collection programme.

Rows are never updated or deleted; a correction is a new row.

id is an autoincrementing integer, not the UUID every other table uses: nothing
else holds a foreign key to a state_history row, and an autoincrement PK gives a
free, portable, strictly-monotonic write order to break ties on -- occurred_at
alone is not reliable for that. Wall-clock resolution on some platforms (observed:
Windows) is coarse enough that two transitions written in the same request can
carry an identical timestamp, which would otherwise make "the latest transition"
ambiguous for time_in_current_stage and win_rate (app/services/state_transitions.py).
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class StateHistory(Base):
    __tablename__ = "state_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunity.id"), nullable=False, index=True)

    field: Mapped[str] = mapped_column(String(32), nullable=False)  # "design_status" | "stage"
    from_value: Mapped[str | None] = mapped_column(String(64), nullable=True)
    to_value: Mapped[str] = mapped_column(String(64), nullable=False)

    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)  # closed vocabulary, WBS 2.6
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    opportunity: Mapped["Opportunity"] = relationship(back_populates="state_events")
