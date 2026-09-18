"""
finding: validation results -- rule, severity, message (WBS 4.0). The Phase 0
output: reproduces the file's data-quality issues as generated findings instead of
documented observations. Blocking findings exclude a row from totals; advisory
findings annotate and let it through (WBS 4.2).
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Finding(Base):
    __tablename__ = "finding"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    opportunity_id: Mapped[str | None] = mapped_column(ForeignKey("opportunity.id"), nullable=True, index=True)
    # Null for a finding raised at direct entry, where there is no sealed file
    # behind the row (WBS 3.7); set for import and workbook findings.
    snapshot_id: Mapped[str | None] = mapped_column(ForeignKey("snapshot.id"), nullable=True, index=True)

    rule_id: Mapped[str] = mapped_column(String(16), nullable=False)  # "V-a".."V-i"
    severity: Mapped[str] = mapped_column(String(16), nullable=False)  # "blocking" | "advisory"
    message: Mapped[str] = mapped_column(String, nullable=False)

    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    opportunity: Mapped["Opportunity"] = relationship(back_populates="findings")
