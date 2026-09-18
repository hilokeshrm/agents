"""
confidence_event: append-only log of every proposal and override, with model ID,
prompt and rubric version stamped per row (WBS 8.0) -- so two runs, or a proposal
versus a human override, can be compared rather than argued about. Never updated.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ConfidenceEvent(Base):
    __tablename__ = "confidence_event"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunity.id"), nullable=False, index=True)
    proposal_id: Mapped[str | None] = mapped_column(ForeignKey("proposal.id"), nullable=True, index=True)
    rubric_version_id: Mapped[str] = mapped_column(ForeignKey("rubric_version.id"), nullable=False, index=True)

    # "proposal" (the agent raised one), "approval"/"rejection" (a reviewer
    # resolved one), "override" (a reviewer supplied their own value), or
    # "auto_applied" (no band crossed, applied without a person).
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)
    base_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    resulting_confidence: Mapped[float] = mapped_column(Float, nullable=False)

    model_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # null for a human override
    prompt_version: Mapped[str | None] = mapped_column(String(32), nullable=True)

    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_role: Mapped[str | None] = mapped_column(String(32), nullable=True)  # written with every mutation (WBS 9.5)
    # An override must cite a code from app/registry/reason_codes.py's
    # override_reason vocabulary -- enforced at the API, which is what makes
    # that draft vocabulary real rather than offered.
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    note: Mapped[str | None] = mapped_column(String, nullable=True)
    # Structured reviewer feedback (WBS 8.7): {"rejected_factors": ["J-05", ...]}
    # on a rejection or override, so rejections aggregate per rubric factor.
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    opportunity: Mapped["Opportunity"] = relationship(back_populates="confidence_events")
