"""Sign-up, one-time-code verification, sign-in and sessions for AUTH_MODE=local.

These routes never take an Actor: they are how a caller becomes one. Role
and scope are looked up from the admin-provisioned app_user row at the end
(see /auth/session) and are never set here.
"""

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.security import local_auth
from app.security.local_auth import AuthError
from app.security.roles import ROLE_LABELS

router = APIRouter(prefix="/auth", tags=["auth"])


class SignupIn(BaseModel):
    email: str
    display_name: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


class EmailIn(BaseModel):
    email: str


class CodeIn(BaseModel):
    email: str
    code: str = Field(min_length=4, max_length=12)


class LoginIn(BaseModel):
    email: str
    password: str


class ResetIn(BaseModel):
    email: str
    code: str
    new_password: str


class OtpOut(BaseModel):
    ok: bool = True
    delivery: str
    # Console delivery only (development): the code, so the flow can be finished
    # without a mailbox. Never populated when delivery is smtp.
    dev_code: str | None = None
    message: str


class TokenOut(BaseModel):
    token: str
    expires_hours: int


class SessionOut(BaseModel):
    email: str
    display_name: str
    email_verified: bool
    # From the admin-provisioned row, when there is one.
    provisioned: bool
    user_id: str | None = None
    role: str | None = None
    role_label: str | None = None
    region_scope: str | None = None


class AuthConfigOut(BaseModel):
    mode: str            # headers | local | oidc
    otp_delivery: str    # console | smtp
    min_password_length: int


def _require_local() -> None:
    if settings.auth_mode != "local":
        raise HTTPException(status_code=404, detail="local sign-in is not enabled (AUTH_MODE is not 'local')")


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="not signed in")
    return authorization.split(" ", 1)[1].strip()


@router.get("/config", response_model=AuthConfigOut)
def config() -> AuthConfigOut:
    mode = "oidc" if settings.auth_issuer else settings.auth_mode
    return AuthConfigOut(mode=mode, otp_delivery=settings.otp_delivery, min_password_length=local_auth.MIN_PASSWORD_LENGTH)


@router.post("/signup", response_model=OtpOut, status_code=201)
def signup(payload: SignupIn, db: Session = Depends(get_db)) -> OtpOut:
    _require_local()
    try:
        _, sent = local_auth.signup(db, payload.email, payload.display_name, payload.password)
        db.commit()
    except AuthError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return OtpOut(delivery=sent.delivery, dev_code=sent.dev_code,
                  message="we sent a 6-digit code to your email; enter it to verify the address")


@router.post("/resend", response_model=OtpOut)
def resend(payload: EmailIn, db: Session = Depends(get_db)) -> OtpOut:
    _require_local()
    try:
        sent = local_auth.resend_code(db, payload.email)
        db.commit()
    except AuthError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return OtpOut(delivery=sent.delivery, dev_code=sent.dev_code, message="if that email has an unverified account, a new code is on its way")


@router.post("/verify", response_model=TokenOut)
def verify(payload: CodeIn, request: Request, db: Session = Depends(get_db)) -> TokenOut:
    _require_local()
    try:
        account = local_auth.verify_email(db, payload.email, payload.code)
        token = local_auth.open_session(db, account, request.headers.get("user-agent"))
        db.commit()
    except AuthError as exc:
        db.commit()  # a wrong attempt is counted even though the request fails
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return TokenOut(token=token, expires_hours=settings.auth_session_hours)


@router.post("/login", response_model=TokenOut)
def login(payload: LoginIn, request: Request, db: Session = Depends(get_db)) -> TokenOut:
    _require_local()
    try:
        account = local_auth.login(db, payload.email, payload.password)
        token = local_auth.open_session(db, account, request.headers.get("user-agent"))
        db.commit()
    except AuthError as exc:
        if exc.status_code == 403 and "verify" in str(exc):
            # Unverified but the password was right: send a fresh code so the
            # person can finish sign-up from the login screen.
            try:
                local_auth.resend_code(db, payload.email)
                db.commit()
            except AuthError:
                db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return TokenOut(token=token, expires_hours=settings.auth_session_hours)


@router.post("/logout", status_code=204)
def logout(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> None:
    _require_local()
    local_auth.revoke_session(db, _bearer(authorization))
    db.commit()


@router.get("/session", response_model=SessionOut)
def session(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> SessionOut:
    """Who this token is, and whether an admin has given that email a role.
    Answers for an unprovisioned account too -- that is how the UI knows to
    show 'ask an admin' rather than a blank pipeline."""
    _require_local()
    try:
        account, _ = local_auth.resolve_session(db, _bearer(authorization))
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    user = local_auth.provisioned_user(db, account)
    if not local_auth.is_usable(user):
        user = None
    return SessionOut(
        email=account.email, display_name=account.display_name,
        email_verified=account.email_verified_at is not None,
        provisioned=user is not None,
        user_id=user.user_id if user else None,
        role=user.role if user else None,
        role_label=ROLE_LABELS.get(user.role) if user else None,
        region_scope=user.region_scope if user else None,
    )


@router.post("/reset/start", response_model=OtpOut)
def reset_start(payload: EmailIn, db: Session = Depends(get_db)) -> OtpOut:
    _require_local()
    try:
        sent = local_auth.start_reset(db, payload.email)
        db.commit()
    except AuthError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return OtpOut(delivery=sent.delivery, dev_code=sent.dev_code, message="if that email has an account, a reset code is on its way")


@router.post("/reset/finish", status_code=204)
def reset_finish(payload: ResetIn, db: Session = Depends(get_db)) -> None:
    _require_local()
    try:
        local_auth.finish_reset(db, payload.email, payload.code, payload.new_password)
        db.commit()
    except AuthError as exc:
        db.commit()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
