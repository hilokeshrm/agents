"""
proposal: pending confidence proposals with factors and quotes -- the review queue
(WBS 7.0, 8.0). Holds the judgment layer's output (app/judgment/rubric.py) before a
person accepts or rejects it; an accepted proposal is what writes a confidence_event.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Proposal(Base):
    __tablename__ = "proposal"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunity.id"), nullable=False, index=True)
    rubric_version_id: Mapped[str] = mapped_column(ForeignKey("rubric_version.id"), nullable=False, index=True)
    # Which run produced this proposal (WBS 10.9). Nullable because a proposal
    # can also be raised for a single row from the review console without a
    # portfolio run behind it.
    run_id: Mapped[str | None] = mapped_column(ForeignKey("run.id"), nullable=True, index=True)

    # "confidence" (the agent proposes a new Confidence Level) or "transition"
    # (the agent proposes a lifecycle move -- Mass Production or Design Lost --
    # for a person to approve, decision #36). Both go through the same queue.
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="confidence")
    # For kind="transition": {"field": "design_status", "to_value": "Mass Production",
    # "reason": "...", "reason_code": ...}. Null for a confidence proposal.
    transition: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    base_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    proposed_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    # list of {rule_id, key, applies, confidence_adjustment_pct, quote, rationale,
    # confidence, accepted, guard, detail, clipped_from} -- the checked reply
    factors: Mapped[list] = mapped_column(JSON, nullable=False)
    # What the bounds did to this proposal: run_cap_clipped_from_pp,
    # clamped_from, contract_violation. Any flag forces the review queue.
    flags: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")  # pending | approved | rejected | overridden | applied
    # True when the proposed value would cross a lifecycle band boundary and so
    # must reach a person (Plate 2, step 9). False means it applied on its own.
    # Null when no ratified bands exist to compare against, which is the state
    # today -- and a null is queued, never auto-applied.
    band_crossing: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)

    opportunity: Mapped["Opportunity"] = relationship(back_populates="proposals")
