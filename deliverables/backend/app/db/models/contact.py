"""
contact: a person at a customer account. Genuinely new -- unlike accounts and
products (both computed rollups over opportunity rows, see app/api/v1/accounts.py
and products.py), contacts are not derivable from anything already on Opportunity.
The real Funnel/ProjectTrack data carries no person-level fields at all, so this
table starts empty and stays empty until someone adds a real contact -- nothing
is seeded here to make the list look populated.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Contact(Base):
    __tablename__ = "contact"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str | None] = mapped_column(String(128), nullable=True)
    account: Mapped[str | None] = mapped_column(String(128), nullable=True)  # matches Opportunity.customer
    email: Mapped[str | None] = mapped_column(String(256), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
