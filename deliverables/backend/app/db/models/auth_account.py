"""Local sign-in (AUTH_MODE=local): an email + password credential with a
one-time code for verification, and the sessions it opens.

This is a *credential*, not an identity with rights. Role and region scope
still come only from the admin-provisioned app_user row that carries the
same email (decision register: no self-registration grants anything). An
account with no such row can sign in and is told to ask an admin.

Nothing secret is stored in clear: the password is a salted PBKDF2 hash,
the one-time code and the session token are stored as SHA-256 digests.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AuthAccount(Base):
    __tablename__ = "auth_account"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(256), unique=True, nullable=False, index=True)  # lower-cased
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)  # pbkdf2_sha256$iters$salt$hash
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # The pending one-time code, if any. purpose: "verify" (after sign-up) or
    # "reset" (forgotten password). Locked after otp_max_attempts wrong tries.
    otp_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    otp_purpose: Mapped[str | None] = mapped_column(String(16), nullable=True)
    otp_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    otp_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    otp_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuthSession(Base):
    __tablename__ = "auth_session"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    account_id: Mapped[str] = mapped_column(String(36), ForeignKey("auth_account.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(256), nullable=True)
