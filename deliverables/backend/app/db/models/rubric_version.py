"""
rubric_version: the published rubric and Matrix A, as versioned config at a point
in time (WBS 2.3, 7.1) -- L4 memory, admin-published. A run stamps this version's
id on every proposal and confidence_event it produces, so two runs can be compared
rather than argued about.

Still blocked on the Q1 (Matrix A ratification) and Q2 (confidence ceiling)
decisions in WBS 1.1 -- this table is where that ratified config lands.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class RubricVersion(Base):
    __tablename__ = "rubric_version"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)

    label: Mapped[str] = mapped_column(String(64), nullable=False)  # e.g. "2026.1"
    matrix_a: Mapped[dict] = mapped_column(JSON, nullable=False)  # valid (design_status, stage) pairs + baseline confidence
    rubric_factors: Mapped[dict] = mapped_column(JSON, nullable=False)  # the RUBRIC list from app/judgment/rubric.py

    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    published_by: Mapped[str] = mapped_column(String(128), nullable=False)
