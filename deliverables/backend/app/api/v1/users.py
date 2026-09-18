"""
Users and provisioning (WBS 9.4, 9.7, 10.8).

Admin-only, and the only way an identity comes into existence on this
platform: there is no sign-up route. Deleting a user anonymises (decision
#85): the name and email go, the user id and every decision made under it
stay, because removing the actor would break the audit chain.
"""

import hashlib
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.app_user import AppUser
from app.db.session import get_db
from app.registry.enums import canonicalize_region
from app.security.oidc import hash_api_key, new_api_key
from app.security.roles import ROLES, Actor, require

router = APIRouter(prefix="/users", tags=["users"])


class UserCreate(BaseModel):
    user_id: str = Field(min_length=2, max_length=128)
    display_name: str
    email: str | None = Field(default=None, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    role: str
    region_scope: str = "*"
    idp_subject: str | None = None
    connector: str | None = None   # service accounts only


class UserUpdate(BaseModel):
    display_name: str | None = None
    role: str | None = None
    region_scope: str | None = None
    active: bool | None = None


class UserRead(BaseModel):
    id: str
    user_id: str
    display_name: str
    email: str | None
    role: str
    region_scope: str
    idp_subject: str | None
    connector: str | None
    active: bool
    provisioned_by: str
    created_at: str
    anonymised_at: str | None


class ServiceKeyRead(UserRead):
    api_key: str   # shown once, at creation; only the hash is stored


def _read(u: AppUser) -> UserRead:
    return UserRead(id=u.id, user_id=u.user_id, display_name=u.display_name, email=u.email, role=u.role,
                    region_scope=u.region_scope, idp_subject=u.idp_subject, connector=u.connector, active=u.active,
                    provisioned_by=u.provisioned_by, created_at=u.created_at.isoformat(),
                    anonymised_at=u.anonymised_at.isoformat() if u.anonymised_at else None)


def _scope(raw: str) -> str:
    raw = raw.strip()
    if raw == "*":
        return "*"
    regions = []
    for part in raw.split(","):
        canon = canonicalize_region(part)
        if canon is None:
            raise HTTPException(status_code=400, detail=f"region {part.strip()!r} is on nobody's list")
        regions.append(canon)
    return ",".join(dict.fromkeys(regions))


@router.get("", response_model=list[UserRead])
def list_users(db: Session = Depends(get_db), actor: Actor = Depends(require("provision_users"))) -> list[UserRead]:
    return [_read(u) for u in db.scalars(select(AppUser).order_by(AppUser.created_at)).all()]


@router.post("", response_model=UserRead, status_code=201)
def provision(payload: UserCreate, db: Session = Depends(get_db),
              actor: Actor = Depends(require("provision_users"))) -> UserRead:
    if payload.role not in ROLES or payload.role == "service":
        raise HTTPException(status_code=400, detail=f"role must be one of {[r for r in ROLES if r != 'service']}; use /users/service for a service account")
    if payload.role == "admin" and payload.region_scope != "*":
        raise HTTPException(status_code=400, detail="admin has no region scope: it sees configuration, not pipeline data")
    if db.scalar(select(AppUser).where(AppUser.user_id == payload.user_id)):
        raise HTTPException(status_code=409, detail="user id already provisioned")
    user = AppUser(user_id=payload.user_id, display_name=payload.display_name,
                   email=payload.email.lower() if payload.email else None, role=payload.role,
                   region_scope=_scope(payload.region_scope), idp_subject=payload.idp_subject,
                   provisioned_by=actor.user_id)
    db.add(user)
    db.commit()
    db.refresh(user)
    return _read(user)


@router.post("/service", response_model=ServiceKeyRead, status_code=201)
def provision_service_account(payload: UserCreate, db: Session = Depends(get_db),
                              actor: Actor = Depends(require("provision_users"))) -> ServiceKeyRead:
    """A service account is scoped to one connector and authenticates with an
    API key shown exactly once. It writes provenanced field values; it never
    enters a confidence, moves a record, or acts as a person (roles matrix)."""
    if not payload.connector:
        raise HTTPException(status_code=400, detail="a service account is scoped to one connector")
    if db.scalar(select(AppUser).where(AppUser.user_id == payload.user_id)):
        raise HTTPException(status_code=409, detail="user id already provisioned")
    key = new_api_key()
    user = AppUser(user_id=payload.user_id, display_name=payload.display_name, role="service",
                   region_scope=_scope(payload.region_scope), connector=payload.connector,
                   api_key_hash=hash_api_key(key), provisioned_by=actor.user_id)
    db.add(user)
    db.commit()
    db.refresh(user)
    return ServiceKeyRead(**vars(_read(user)), api_key=key)


@router.patch("/{user_id}", response_model=UserRead)
def update_user(user_id: str, payload: UserUpdate, db: Session = Depends(get_db),
                actor: Actor = Depends(require("provision_users"))) -> UserRead:
    user = db.scalar(select(AppUser).where(AppUser.user_id == user_id))
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    if payload.role is not None:
        if payload.role not in ROLES:
            raise HTTPException(status_code=400, detail="unknown role")
        user.role = payload.role
    if payload.region_scope is not None:
        user.region_scope = _scope(payload.region_scope)
    if payload.display_name is not None:
        user.display_name = payload.display_name
    if payload.active is not None:
        user.active = payload.active
    db.commit()
    db.refresh(user)
    return _read(user)


@router.delete("/{user_id}", response_model=UserRead)
def anonymise_user(user_id: str, db: Session = Depends(get_db),
                   actor: Actor = Depends(require("provision_users"))) -> UserRead:
    """WBS 9.7 / decision #85: deleting an account anonymises the display
    identity and deactivates the login. The user id -- the actor written on
    every audit row -- stays, and so does every decision."""
    user = db.scalar(select(AppUser).where(AppUser.user_id == user_id))
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    if user.user_id == actor.user_id:
        raise HTTPException(status_code=400, detail="an admin cannot anonymise their own account from inside it")
    digest = hashlib.sha256(user.user_id.encode()).hexdigest()[:10]
    user.display_name = f"former user {digest}"
    user.email = None
    user.idp_subject = None
    user.api_key_hash = None
    user.active = False
    user.anonymised_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)
    return _read(user)
