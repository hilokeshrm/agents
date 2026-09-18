"""
Users & access (WBS 10.8), and the identity the rest of the UI reads its own
permissions from (WBS 10.10, per-role landing views).

There is no user table here and none is invented. Accounts are provisioned
against the corporate directory (WBS 9.4, To do), so the "people" this screen can
honestly show are the identities that actually appear in the data: opportunity
owners, and the actors on state_history and confidence_event rows. Those are
observed facts. A provisioned-user list with roles and last-active times would be
a fabrication of exactly the kind this codebase refuses everywhere else, so
/access/actors reports what the audit trail contains and says so.

The permission matrix, by contrast, is real and enforced -- app/security/roles.py
is the single copy, and this router serves it rather than the UI keeping a second.
"""

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.confidence_event import ConfidenceEvent
from app.db.models.opportunity import Opportunity
from app.db.models.state_history import StateHistory
from app.db.session import get_db
from app.security.roles import (
    ACTION_LABELS,
    GRANT_ALLOWS,
    PERMISSIONS,
    ROLE_LABELS,
    ROLES,
    Actor,
    current_actor,
)

router = APIRouter(prefix="/access", tags=["access"])


class MatrixRow(BaseModel):
    action: str
    label: str
    grants: dict[str, str]


class MatrixRead(BaseModel):
    roles: list[str]
    role_labels: dict[str, str]
    allows: list[str]
    rows: list[MatrixRow]
    enforcement: list[dict]


class MeRead(BaseModel):
    user_id: str
    role: str
    role_label: str
    regions: list[str]
    sees_all_regions: bool
    grants: dict[str, str]
    identity_source: str


class ActorRead(BaseModel):
    name: str
    appears_as: list[str]  # owner | state_history actor | confidence_event actor
    opportunities_owned: int
    events: int
    last_seen: datetime | None


# The six enforcement points from the product document's Users & access section.
# Listed with where each one actually lives, so the screen can say which are
# built and which are waiting on SSO rather than implying all six are running.
ENFORCEMENT = [
    {"n": 1, "point": "Identity", "detail": "SSO assertion -> role + region scope, never self-set",
     "where": "app/security/roles.py:current_actor", "status": "stand-in: read from request headers (WBS 9.4 to do)"},
    {"n": 2, "point": "Query", "detail": "every SELECT is wrapped by region scope, not filtered in the UI",
     "where": "app/security/roles.py:scope_opportunities", "status": "built"},
    {"n": 3, "point": "Route", "detail": "a dependency asserts the role before the handler runs",
     "where": "app/security/roles.py:require", "status": "built"},
    {"n": 4, "point": "Field", "detail": "confidence is never a PATCHable field on an opportunity",
     "where": "no PATCH route exists; confidence changes only via a resolved proposal", "status": "built"},
    {"n": 5, "point": "Decision", "detail": "a reviewer cannot resolve a proposal on a row they own",
     "where": "app/services/proposals.py:resolve_proposal", "status": "built"},
    {"n": 6, "point": "Audit", "detail": "actor and role written with every mutation, before it returns",
     "where": "confidence_event.actor / actor_role", "status": "built for confidence events; "
                                                            "state_history records the actor, role once SSO lands"},
]


@router.get("/matrix", response_model=MatrixRead)
def matrix() -> MatrixRead:
    return MatrixRead(
        roles=list(ROLES),
        role_labels=ROLE_LABELS,
        allows=sorted(GRANT_ALLOWS),
        rows=[
            MatrixRow(action=action, label=ACTION_LABELS[action], grants=grants)
            for action, grants in PERMISSIONS.items()
        ],
        enforcement=ENFORCEMENT,
    )


@router.get("/me", response_model=MeRead)
def me(actor: Actor = Depends(current_actor)) -> MeRead:
    return MeRead(
        user_id=actor.user_id,
        role=actor.role,
        role_label=ROLE_LABELS[actor.role],
        regions=list(actor.regions),
        sees_all_regions=actor.sees_all_regions,
        grants={action: actor.grant(action) for action in PERMISSIONS},
        identity_source="request header (development stand-in; SSO is WBS 9.4)",
    )


@router.get("/actors", response_model=list[ActorRead])
def actors(db: Session = Depends(get_db)) -> list[ActorRead]:
    """Identities observed in the data, not a provisioned user list."""
    seen: dict[str, dict] = {}

    def touch(name: str, kind: str, when: datetime | None = None) -> None:
        entry = seen.setdefault(name, {"appears_as": set(), "owned": 0, "events": 0, "last": None})
        entry["appears_as"].add(kind)
        if when is not None and (entry["last"] is None or when > entry["last"]):
            entry["last"] = when

    for owner, in db.execute(select(Opportunity.owner)).all():
        if owner:
            touch(owner, "opportunity owner")
            seen[owner]["owned"] += 1

    for event in db.scalars(select(StateHistory)).all():
        touch(event.actor, "state history", event.occurred_at)
        seen[event.actor]["events"] += 1

    for event in db.scalars(select(ConfidenceEvent)).all():
        touch(event.actor, "confidence event", event.occurred_at)
        seen[event.actor]["events"] += 1

    return sorted(
        (
            ActorRead(
                name=name, appears_as=sorted(data["appears_as"]),
                opportunities_owned=data["owned"], events=data["events"], last_seen=data["last"],
            )
            for name, data in seen.items()
        ),
        key=lambda a: (-a.opportunities_owned, a.name),
    )
