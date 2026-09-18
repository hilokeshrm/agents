"""
run: one execution of the ten-step judgment pass, with its step trace
(docs/02-architecture/OppTrack_Layer_Diagrams.html, Plate 2) -- the table behind
the Runs & audit screen (WBS 10.9).

The twelfth table, and the only one added after WBS 9.1's ten. It exists because
"a run is a pure function of a snapshot, so it can be opened, read step by step,
and re-executed to the same numbers" needs somewhere to keep the steps. Storing
the trace as JSON rather than a step table is deliberate: a step's shape is the
run's own record of what it did, not a queryable dimension, and a schema change
every time a step gains a field would be the wrong kind of coupling.

A failed run is written, not swallowed. The product document is explicit that a
run which raised rather than silently substituting a mock scorer is a successful
outcome of the design, and hiding it would remove the only evidence the guard
worked.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Run(Base):
    __tablename__ = "run"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)

    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="judgment")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")  # running | completed | failed
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="mock")  # live | mock -- which scorer actually ran

    rubric_version_id: Mapped[str] = mapped_column(ForeignKey("rubric_version.id"), nullable=False, index=True)
    # Null when the run scored live opportunity rows rather than a sealed
    # workbook snapshot. Not a placeholder: the two are genuinely different
    # inputs, and pretending a live-row run had a snapshot would break the
    # reproducibility claim the snapshot table exists to make.
    snapshot_id: Mapped[str | None] = mapped_column(ForeignKey("snapshot.id"), nullable=True, index=True)

    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    steps: Mapped[list] = mapped_column(JSON, nullable=False, default=list)  # [{n, name, detail, status, lane}]
    counts: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(String, nullable=True)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
