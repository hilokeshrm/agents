"""
opportunity: the row identity, owner, region scope. Every other table's foreign key
(docs/02-architecture/OppTrack_Complete_Architecture.html, section 12).

The primary key remains a UUID for internal references. `external_id` is the stable,
human-facing key used for workbook/CRM crosswalks and review conversations.
"""

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import JSON, Date, DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _external_id() -> str:
    """Fallback only: rows created without next_external_id() (tests that build
    an Opportunity directly) get a random id rather than a colliding one. The
    intake paths call next_external_id() for the sequential OPP-000001 form."""
    return f"OPP-{uuid.uuid4().hex[:12].upper()}"


EXTERNAL_ID_WIDTH = 6


def next_external_id(db) -> str:
    """Decision #56: a human-readable, sequential id, minted from
    opportunity_sequence so it is unique under concurrency and identical on
    SQLite and Postgres."""
    from app.db.models.opportunity_sequence import OpportunitySequence

    row = OpportunitySequence()
    db.add(row)
    db.flush()
    return f"OPP-{row.id:0{EXTERNAL_ID_WIDTH}d}"


class Opportunity(Base):
    __tablename__ = "opportunity"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    external_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, default=_external_id, index=True)

    region: Mapped[str] = mapped_column(String(64), nullable=False)
    customer: Mapped[str] = mapped_column(String(128), nullable=False)
    end_customer: Mapped[str] = mapped_column(String(128), nullable=False)
    project: Mapped[str] = mapped_column(String(128), nullable=False)
    application: Mapped[str | None] = mapped_column(String(128), nullable=True)  # V5
    product_line: Mapped[str | None] = mapped_column(String(128), nullable=True)  # V6
    part_number: Mapped[str] = mapped_column(String(64), nullable=False)

    design_status: Mapped[str] = mapped_column(String(64), nullable=False)
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    mp_date: Mapped[date | None] = mapped_column(Date, nullable=True)  # V10; mass-production start date

    eau_kpcs: Mapped[float] = mapped_column(Float, nullable=False)
    unit_set: Mapped[float | None] = mapped_column(Float, nullable=True)  # V12; feeds C3/C4, WBS 5.2
    disty_asp: Mapped[float] = mapped_column(Float, nullable=False)
    # Non-recurring engineering charge in $K (V29): one-off engineering work or a
    # licence, not silicon revenue. Nullable because most opportunities carry
    # none, and a null here means "no NRE on this row", never zero-by-default.
    nre_charge_k: Mapped[float | None] = mapped_column(Float, nullable=True)
    resale_asp: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Per-opportunity volume profile, {"2025": [q1..q4], ...} in Kpcs (decision
    # #66, WBS 5.5). When present it is the phasing basis; otherwise the M/P
    # ramp; otherwise the row reports unphased.
    phasing_profile: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    competitor_part: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Row-level region/owner scope (WBS 9.5 injects this at the query level, not here).
    owner: Mapped[str] = mapped_column(String(128), nullable=False)
    evidence: Mapped[str | None] = mapped_column(String, nullable=True)
    confidence_rationale: Mapped[str] = mapped_column(String, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )

    state_events: Mapped[list["StateHistory"]] = relationship(back_populates="opportunity")
    owner_events: Mapped[list["OwnerHistory"]] = relationship(back_populates="opportunity")
    field_values: Mapped[list["FieldValue"]] = relationship(back_populates="opportunity")
    forecasts: Mapped[list["Forecast"]] = relationship(back_populates="opportunity")
    proposals: Mapped[list["Proposal"]] = relationship(back_populates="opportunity")
    confidence_events: Mapped[list["ConfidenceEvent"]] = relationship(back_populates="opportunity")
    findings: Mapped[list["Finding"]] = relationship(back_populates="opportunity")
