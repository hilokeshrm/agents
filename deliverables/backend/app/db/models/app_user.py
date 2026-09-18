"""
app_user: admin-provisioned identities (WBS 9.4, R4 identity).

No public sign-up, no self-registration: a row exists because an admin
created it against the corporate directory, and the role and region scope on
it are what the platform enforces -- never a claim the caller supplied. SSO
proves *who* is calling (the idp_subject); this table decides what they may
do. Service accounts are rows with role "service" and a hashed API key, scoped
to one connector.

Deletion anonymises (WBS 9.7, decision #85): the display name and email are
replaced, `anonymised_at` is set, and every decision the person made stays in
the audit tables under their user id -- removing the actor would break the
chain the audit trail exists to keep.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AppUser(Base):
    __tablename__ = "app_user"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)   # the actor id written to audit rows
    email: Mapped[str | None] = mapped_column(String(256), unique=True, nullable=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    region_scope: Mapped[str] = mapped_column(String(256), nullable=False, default="*")   # "*" or "Korea,Europe"
    idp_subject: Mapped[str | None] = mapped_column(String(256), unique=True, nullable=True, index=True)
    api_key_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)  # service accounts
    connector: Mapped[str | None] = mapped_column(String(64), nullable=True)                 # a service account's one connector
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    provisioned_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now, nullable=False)
    anonymised_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def regions(self) -> tuple[str, ...]:
        scope = (self.region_scope or "*").strip()
        return () if scope == "*" else tuple(r.strip() for r in scope.split(",") if r.strip())
