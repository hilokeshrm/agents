"""
Six roles, their permissions, and region scope (WBS 9.5; the matrix is
docs/02-architecture/OppTrack_Product_Surface.html, "Users & access").

Two things here are real and one is deliberately not:

REAL -- the permission matrix and its enforcement. PERMISSIONS below is that
document's table transcribed cell for cell, and `require()` is a FastAPI
dependency that runs *before the handler*, which is enforcement point 3 of the
six the document lists. `scope_opportunities()` is point 2: it wraps the SELECT,
so an out-of-scope row is a 404 rather than a row filtered out of a response the
query already fetched. Point 5 (a reviewer cannot approve their own row) lives
in app/services/proposals.py, in code, not in the interface.

NOT REAL YET -- where the identity comes from. Enforcement point 1 is an SSO
assertion (WBS 9.4, To do): role and region scope come from the corporate
directory and are never self-set. Until that exists, current_actor() reads them
from request headers, which means any caller can claim any role. That is a
development stand-in, not an access control system, and it is why this module is
not a security boundary today -- the same caveat the README already carries for
/dev. Building it now means every route, query and decision is written against
the real contract, so 9.4 replaces one function instead of touching every handler.
"""

from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db

ROLES = ("owner", "manager", "director", "finance", "admin", "service")

# Grant vocabulary, verbatim from the document's matrix. Anything other than
# "yes"/"own_region"/"all_regions" denies the action: "scoped", "fields_only"
# and "scheduled" all describe a service account's non-interactive path, which
# no human-facing route grants (WBS 10.12 and 11.x own those), and "never" is
# the document's emphatic no on a service account entering a confidence value.
GRANT_ALLOWS = {"yes", "own_region", "all_regions"}

# action -> role -> grant. Row order matches the document's table.
PERMISSIONS: dict[str, dict[str, str]] = {
    "view_own_region": {"owner": "yes", "manager": "yes", "director": "yes", "finance": "yes", "admin": "no", "service": "scoped"},
    "view_all_regions": {"owner": "no", "manager": "no", "director": "yes", "finance": "yes", "admin": "no", "service": "no"},
    "create_edit_opportunity": {"owner": "yes", "manager": "yes", "director": "yes", "finance": "no", "admin": "no", "service": "fields only"},
    "enter_confidence_at_intake": {"owner": "yes", "manager": "yes", "director": "yes", "finance": "no", "admin": "no", "service": "never"},
    "move_stage_status": {"owner": "yes", "manager": "yes", "director": "yes", "finance": "no", "admin": "no", "service": "no"},
    "attach_evidence": {"owner": "yes", "manager": "yes", "director": "yes", "finance": "no", "admin": "no", "service": "no"},
    "request_review": {"owner": "yes", "manager": "yes", "director": "yes", "finance": "no", "admin": "no", "service": "no"},
    "approve_reject_proposal": {"owner": "no", "manager": "own_region", "director": "all_regions", "finance": "no", "admin": "no", "service": "no"},
    "override_with_own_value": {"owner": "no", "manager": "own_region", "director": "all_regions", "finance": "no", "admin": "no", "service": "no"},
    "close_design_lost": {"owner": "no", "manager": "own_region", "director": "all_regions", "finance": "no", "admin": "no", "service": "no"},
    "pull_forecast_feed": {"owner": "no", "manager": "yes", "director": "yes", "finance": "yes", "admin": "no", "service": "scoped"},
    "trigger_run": {"owner": "no", "manager": "no", "director": "no", "finance": "no", "admin": "yes", "service": "scheduled"},
    "publish_rubric": {"owner": "no", "manager": "no", "director": "no", "finance": "no", "admin": "yes", "service": "no"},
    "provision_users": {"owner": "no", "manager": "no", "director": "no", "finance": "no", "admin": "yes", "service": "no"},
    # The one row that is "no" for every role, admin included. Nothing in this
    # codebase updates or deletes a state_history, confidence_event or finding row.
    "edit_audit_entry": {"owner": "no", "manager": "no", "director": "no", "finance": "no", "admin": "no", "service": "no"},
}

# Human labels for the same rows, so the admin screen renders this table rather
# than a second, hand-maintained copy of it.
ACTION_LABELS = {
    "view_own_region": "View own region",
    "view_all_regions": "View all regions",
    "create_edit_opportunity": "Create / edit opportunity",
    "enter_confidence_at_intake": "Enter confidence at intake",
    "move_stage_status": "Move stage / status",
    "attach_evidence": "Attach evidence",
    "request_review": "Request a review",
    "approve_reject_proposal": "Approve / reject proposal",
    "override_with_own_value": "Override with own value",
    "close_design_lost": "Close / mark Design Lost",
    "pull_forecast_feed": "Pull forecast feed",
    "trigger_run": "Trigger a run",
    "publish_rubric": "Publish rubric / Matrix A",
    "provision_users": "Provision users, set scope",
    "edit_audit_entry": "Edit an audit entry",
}

ROLE_LABELS = {
    "owner": "Regional sales owner",
    "manager": "Sales manager",
    "director": "Regional director",
    "finance": "Finance",
    "admin": "Admin",
    "service": "Service account",
}

ALL_REGIONS = "*"


@dataclass(frozen=True)
class Actor:
    """Who is calling, and what they may see. Assembled from headers today; from
    an SSO assertion once WBS 9.4 lands (see the module docstring)."""

    user_id: str
    role: str
    regions: tuple[str, ...]  # empty tuple == every region (the "all regions" scope)

    @property
    def sees_all_regions(self) -> bool:
        return not self.regions

    def grant(self, action: str) -> str:
        return PERMISSIONS[action][self.role]

    def can(self, action: str) -> bool:
        return self.grant(action) in GRANT_ALLOWS

    def can_act_on_region(self, action: str, region: str) -> bool:
        """`own_region` grants are why this is separate from can(): a manager may
        approve inside their scope and nowhere else."""
        grant = self.grant(action)
        if grant not in GRANT_ALLOWS:
            return False
        if grant == "own_region":
            return self.sees_all_regions or region in self.regions
        return True

    def in_scope(self, region: str) -> bool:
        return self.sees_all_regions or region in self.regions


def current_actor(
    x_opptrack_actor: str | None = Header(default=None),
    x_opptrack_role: str | None = Header(default=None),
    x_opptrack_regions: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
    x_opptrack_api_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> Actor:
    """Enforcement point 1 (WBS 9.4). With `auth_issuer` configured, the caller
    is a Bearer token the identity provider signed or a service account's API
    key, and role and scope come from the admin-provisioned app_user row.
    Without it, the development header stand-in below applies -- and says so."""
    if settings.auth_issuer:
        return _actor_from_credentials(db, authorization, x_opptrack_api_key)
    if settings.auth_mode == "local":
        return _actor_from_local_session(db, authorization, x_opptrack_api_key)
    role = (x_opptrack_role or settings.dev_default_role).lower()
    if role not in ROLES:
        raise HTTPException(status_code=400, detail=f"unknown role {role!r}; expected one of {list(ROLES)}")

    raw_regions = x_opptrack_regions if x_opptrack_regions is not None else settings.dev_default_regions
    regions: tuple[str, ...] = ()
    if raw_regions and raw_regions.strip() != ALL_REGIONS:
        regions = tuple(r.strip() for r in raw_regions.split(",") if r.strip())

    return Actor(
        user_id=x_opptrack_actor or settings.dev_default_actor,
        role=role,
        regions=regions,
    )


def _actor_from_credentials(db: Session, authorization: str | None, api_key: str | None) -> Actor:
    from app.db.models.app_user import AppUser
    from app.security.oidc import AuthError, hash_api_key, verify_bearer

    user: AppUser | None = None
    if api_key:
        user = db.scalar(select(AppUser).where(AppUser.api_key_hash == hash_api_key(api_key)))
        if user is None or user.role != "service":
            raise HTTPException(status_code=401, detail="unknown API key")
    elif authorization and authorization.lower().startswith("bearer "):
        try:
            identity = verify_bearer(authorization.split(" ", 1)[1].strip())
        except AuthError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        user = db.scalar(select(AppUser).where(AppUser.idp_subject == identity.subject))
        if user is None and identity.email:
            # First sign-in of a provisioned user: bind the subject to the row
            # the admin created by email. Never creates a row.
            user = db.scalar(select(AppUser).where(AppUser.email == identity.email.lower(), AppUser.idp_subject.is_(None)))
            if user is not None:
                user.idp_subject = identity.subject
                db.commit()   # the binding outlives this request whatever the route does
        if user is None:
            raise HTTPException(
                status_code=403,
                detail="signed in, but not provisioned on this platform -- there is no self-registration; ask an admin",
            )
    else:
        raise HTTPException(status_code=401, detail="a Bearer token or an API key is required")
    if not user.active or user.anonymised_at is not None:
        raise HTTPException(status_code=403, detail="account is deactivated")
    return Actor(user_id=user.user_id, role=user.role, regions=user.regions)


def _actor_from_local_session(db: Session, authorization: str | None, api_key: str | None) -> Actor:
    """AUTH_MODE=local: a session token from /auth/login or /auth/verify, or a
    service account's API key. The X-OppTrack-* headers are ignored entirely.
    Role and scope come from the app_user row that carries the account's email."""
    from app.db.models.app_user import AppUser
    from app.security.local_auth import AuthError, provisioned_user, resolve_session
    from app.security.oidc import hash_api_key

    if api_key:
        user = db.scalar(select(AppUser).where(AppUser.api_key_hash == hash_api_key(api_key)))
        if user is None or user.role != "service":
            raise HTTPException(status_code=401, detail="unknown API key")
    elif authorization and authorization.lower().startswith("bearer "):
        try:
            account, _ = resolve_session(db, authorization.split(" ", 1)[1].strip())
        except AuthError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        user = provisioned_user(db, account)
        if user is None:
            raise HTTPException(
                status_code=403,
                detail="signed in, but no role has been assigned to this email yet -- ask an admin to provision it",
            )
        if not user.active or user.anonymised_at is not None:
            raise HTTPException(status_code=403, detail="account is deactivated")
    else:
        raise HTTPException(status_code=401, detail="sign in first")
    if not user.active or user.anonymised_at is not None:
        raise HTTPException(status_code=403, detail="account is deactivated")
    return Actor(user_id=user.user_id, role=user.role, regions=user.regions)


def require(action: str):
    """Route dependency asserting the role before the handler runs -- enforcement
    point 3. Region-sensitive decisions (`own_region` grants) need the row's
    region, so those call actor.can_act_on_region() inside the handler."""

    def dependency(actor: Actor = Depends(current_actor)) -> Actor:
        if not actor.can(action):
            raise HTTPException(
                status_code=403,
                detail=f"role {actor.role!r} may not {ACTION_LABELS.get(action, action)!r} "
                       f"(grant: {actor.grant(action)})",
            )
        return actor

    return dependency


def scope_opportunities(stmt: Select, model, actor: Actor) -> Select:
    """Enforcement point 2: wrap the SELECT rather than filter the response.
    A role with no view grant at all (admin) sees nothing, which is the
    document's "pipeline data by default" denial, not an oversight."""
    if not actor.can("view_own_region") and not actor.can("view_all_regions"):
        return stmt.where(model.region.is_(None))  # matches nothing; region is NOT NULL
    if actor.sees_all_regions:
        return stmt
    return stmt.where(model.region.in_(actor.regions))


def assert_visible(region: str, actor: Actor) -> None:
    """404, never 403: a 403 would confirm the row exists, which is itself a
    disclosure when the data is unannounced design wins and customer pricing."""
    if not actor.in_scope(region) or not (actor.can("view_own_region") or actor.can("view_all_regions")):
        raise HTTPException(status_code=404, detail="Opportunity not found")
