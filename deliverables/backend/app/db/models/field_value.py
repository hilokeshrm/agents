"""
field_value: provenanced values from CRM, ERP, POS and every other connector
(WBS 3.6) -- FieldValue(param, value, source, at, trust) from
docs/02-architecture/OppTrack_Complete_Architecture.html section 10. Never
overwrites a human edit silently: direct-entry values carry the highest trust
level, above every connector (see project memory opptrack-intake-not-excel).
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

# Higher number = more trusted. The precedence ladder of decision #63:
# human edit > ERP > CRM > distributor POS/POR > workbook import > inferred.
# A lower tier never overwrites a higher one silently; it raises a
# reconciliation item (app/connectors/_framework.py).
TRUST_LEVELS = {
    "inferred": 0,
    "market": 0,
    "import": 1,
    "pos": 2,
    "crm": 3,
    "erp": 4,
    "direct_entry": 5,
    "human_reconciled": 5,
}


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class FieldValue(Base):
    __tablename__ = "field_value"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    opportunity_id: Mapped[str] = mapped_column(ForeignKey("opportunity.id"), nullable=False, index=True)

    param: Mapped[str] = mapped_column(String(16), nullable=False)  # ParamSpec id, e.g. "V1" -- never a column name
    value: Mapped[str] = mapped_column(String, nullable=False)  # serialized; dtype comes from the ParamSpec registry
    source: Mapped[str] = mapped_column(String(64), nullable=False)  # connector or "direct_entry"
    trust: Mapped[int] = mapped_column(Integer, nullable=False)  # see TRUST_LEVELS

    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)

    opportunity: Mapped["Opportunity"] = relationship(back_populates="field_values")
