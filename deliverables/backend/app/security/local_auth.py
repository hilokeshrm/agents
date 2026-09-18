"""Local sign-in: email + password, a one-time code by mail to prove the
address, and opaque revocable sessions. Active when AUTH_MODE=local.

What it deliberately does not do: grant a role. Signing up creates a
credential. The role and region scope a signed-in person acts with come
from the app_user row an admin provisioned for that email -- the same row
OIDC binds to (app/security/roles.py). No row, no rights: the session is
valid, /auth/session says provisioned=false, and every pipeline route
answers 403 with "ask an admin".

Password hashing is PBKDF2-HMAC-SHA256 from the standard library (no
native dependency to build on Windows); the one-time code and the session
token are stored only as SHA-256 digests.
"""

import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models.app_user import AppUser
from app.db.models.auth_account import AuthAccount, AuthSession
from app.services.mail import MailError, send_email

log = logging.getLogger("opptrack.auth")

PBKDF2_ITERATIONS = 210_000
MIN_PASSWORD_LENGTH = 10
OTP_DIGITS = 6
OTP_MAX_ATTEMPTS = 5
OTP_RESEND_SECONDS = 45


class AuthError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    # SQLite hands naive datetimes back; the column is declared timezone-aware.
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# --- passwords -------------------------------------------------------------

def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AuthError(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PBKDF2_ITERATIONS).hex()
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt, digest = stored.split("$", 3)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations)).hex()
    return hmac.compare_digest(candidate, digest)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


# --- one-time codes ----------------------------------------------------------

@dataclass
class OtpDelivery:
    delivery: str          # "console" | "smtp"
    dev_code: str | None   # only with console delivery: the code itself, so a developer can finish the flow


def _issue_otp(db: Session, account: AuthAccount, purpose: str) -> OtpDelivery:
    now = _now()
    sent = _aware(account.otp_sent_at)
    if sent is not None and (now - sent).total_seconds() < OTP_RESEND_SECONDS and account.otp_purpose == purpose:
        raise AuthError(f"a code was sent moments ago; wait {OTP_RESEND_SECONDS} seconds before asking for another", 429)
    code = "".join(secrets.choice("0123456789") for _ in range(OTP_DIGITS))
    account.otp_hash = _digest(code)
    account.otp_purpose = purpose
    account.otp_expires_at = now + timedelta(minutes=settings.otp_ttl_minutes)
    account.otp_sent_at = now
    account.otp_attempts = 0
    db.flush()

    what = "verify your email address" if purpose == "verify" else "reset your password"
    body = (
        f"Hello {account.display_name},\n\n"
        f"Your Opportunity Tracking code to {what} is:\n\n    {code}\n\n"
        f"It expires in {settings.otp_ttl_minutes} minutes. If you did not ask for it, ignore this message.\n"
    )
    try:
        delivery = send_email(account.email, "Your Opportunity Tracking sign-in code", body)
    except MailError as exc:
        raise AuthError(str(exc), 502) from exc
    log.info("otp issued purpose=%s account=%s delivery=%s", purpose, account.email, delivery)
    return OtpDelivery(delivery=delivery, dev_code=code if delivery == "console" else None)


def _check_otp(account: AuthAccount, code: str, purpose: str) -> None:
    if not account.otp_hash or account.otp_purpose != purpose:
        raise AuthError("no code is pending for this account; request a new one", 400)
    if account.otp_attempts >= OTP_MAX_ATTEMPTS:
        raise AuthError("too many wrong codes; request a new one", 423)
    expires = _aware(account.otp_expires_at)
    if expires is None or _now() > expires:
        raise AuthError("the code has expired; request a new one", 410)
    if not hmac.compare_digest(_digest(code.strip()), account.otp_hash):
        account.otp_attempts += 1
        left = OTP_MAX_ATTEMPTS - account.otp_attempts
        raise AuthError(f"wrong code; {left} attempt(s) left" if left else "too many wrong codes; request a new one", 401)
    account.otp_hash = None
    account.otp_purpose = None
    account.otp_expires_at = None
    account.otp_attempts = 0


# --- accounts ----------------------------------------------------------------

def normalise_email(email: str) -> str:
    email = email.strip().lower()
    if "@" not in email or email.startswith("@") or email.endswith("@") or " " in email:
        raise AuthError("that does not look like an email address")
    return email


def get_account(db: Session, email: str) -> AuthAccount | None:
    return db.scalar(select(AuthAccount).where(AuthAccount.email == normalise_email(email)))


def signup(db: Session, email: str, display_name: str, password: str) -> tuple[AuthAccount, OtpDelivery]:
    email = normalise_email(email)
    display_name = display_name.strip()
    if not display_name:
        raise AuthError("a display name is required")
    existing = get_account(db, email)
    if existing is not None:
        if existing.email_verified_at is not None:
            raise AuthError("an account with that email already exists; sign in instead", 409)
        # Unverified re-signup: refresh the credential and send a fresh code.
        existing.display_name = display_name
        existing.password_hash = hash_password(password)
        existing.otp_sent_at = None
        return existing, _issue_otp(db, existing, "verify")
    account = AuthAccount(email=email, display_name=display_name, password_hash=hash_password(password))
    db.add(account)
    db.flush()
    return account, _issue_otp(db, account, "verify")


def resend_code(db: Session, email: str, purpose: str = "verify") -> OtpDelivery:
    account = get_account(db, email)
    if account is None:
        # Same answer as success so the endpoint does not reveal which emails exist.
        return OtpDelivery(delivery=settings.otp_delivery, dev_code=None)
    if purpose == "verify" and account.email_verified_at is not None:
        raise AuthError("this email is already verified; sign in", 409)
    account.otp_sent_at = None if purpose != account.otp_purpose else account.otp_sent_at
    return _issue_otp(db, account, purpose)


def verify_email(db: Session, email: str, code: str) -> AuthAccount:
    account = get_account(db, email)
    if account is None:
        raise AuthError("wrong code", 401)
    _check_otp(account, code, "verify")
    account.email_verified_at = _now()
    db.flush()
    return account


def login(db: Session, email: str, password: str) -> AuthAccount:
    account = get_account(db, email)
    # One generic answer for unknown email and wrong password.
    if account is None or not verify_password(password, account.password_hash):
        raise AuthError("email or password is wrong", 401)
    if not account.active:
        raise AuthError("this account is deactivated", 403)
    if account.email_verified_at is None:
        raise AuthError("verify your email first -- we have sent you a new code", 403)
    account.last_login_at = _now()
    db.flush()
    return account


def start_reset(db: Session, email: str) -> OtpDelivery:
    return resend_code(db, email, purpose="reset")


def finish_reset(db: Session, email: str, code: str, new_password: str) -> AuthAccount:
    account = get_account(db, email)
    if account is None:
        raise AuthError("wrong code", 401)
    _check_otp(account, code, "reset")
    account.password_hash = hash_password(new_password)
    account.email_verified_at = account.email_verified_at or _now()
    # A reset invalidates every open session.
    for s in db.scalars(select(AuthSession).where(AuthSession.account_id == account.id, AuthSession.revoked_at.is_(None))):
        s.revoked_at = _now()
    db.flush()
    return account


# --- sessions ----------------------------------------------------------------

def open_session(db: Session, account: AuthAccount, user_agent: str | None = None) -> str:
    token = secrets.token_urlsafe(32)
    db.add(AuthSession(
        account_id=account.id, token_hash=_digest(token),
        expires_at=_now() + timedelta(hours=settings.auth_session_hours),
        user_agent=(user_agent or "")[:256] or None,
    ))
    db.flush()
    return token


def resolve_session(db: Session, token: str) -> tuple[AuthAccount, AuthSession]:
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == _digest(token)))
    if session is None or session.revoked_at is not None:
        raise AuthError("not signed in", 401)
    if _now() > _aware(session.expires_at):
        raise AuthError("session expired; sign in again", 401)
    account = db.get(AuthAccount, session.account_id)
    if account is None or not account.active:
        raise AuthError("this account is deactivated", 403)
    return account, session


def revoke_session(db: Session, token: str) -> None:
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == _digest(token)))
    if session is not None and session.revoked_at is None:
        session.revoked_at = _now()
        db.flush()


def provisioned_user(db: Session, account: AuthAccount) -> AppUser | None:
    """The admin-provisioned row that gives this credential its role, if any --
    including a deactivated one, so the caller can say "deactivated" rather
    than "not provisioned"."""
    return db.scalar(select(AppUser).where(AppUser.email == account.email))


def is_usable(user: AppUser | None) -> bool:
    return user is not None and user.active and user.anonymised_at is None
