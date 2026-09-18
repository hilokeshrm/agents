"""
Append-only tables, enforced at the ORM (WBS 8.2, R4 auditability).

confidence_event, state_history, owner_history and snapshot are the audit
trail behind every figure a reviewer approves. "Nobody can edit an audit
entry" is a property of the schema here, not a promise: any attempt to UPDATE
or DELETE a row in one of these tables through a session raises before the
statement is emitted, for every role including admin, because the check does
not know what a role is.

This does not stop raw SQL against the database -- that is a database-grant
matter for WBS 9.7 (retention) and 13.x (operations). What it stops is any
code path in this application, present or future, quietly rewriting history.
"""

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.db.models.confidence_event import ConfidenceEvent
from app.db.models.owner_history import OwnerHistory
from app.db.models.snapshot import Snapshot
from app.db.models.state_history import StateHistory

APPEND_ONLY = (ConfidenceEvent, StateHistory, OwnerHistory, Snapshot)


class ImmutableRowError(RuntimeError):
    """Raised on any attempt to update or delete an append-only row."""


def _refuse(mapper, connection, target) -> None:  # noqa: ARG001 -- SQLAlchemy listener signature
    raise ImmutableRowError(
        f"{type(target).__tablename__} is append-only: rows are never updated or deleted "
        f"(id={getattr(target, 'id', None)!r}). Write a new row instead."
    )


for model in APPEND_ONLY:
    event.listen(model, "before_update", _refuse)
    event.listen(model, "before_delete", _refuse)


@event.listens_for(Session, "before_flush")
def _refuse_dirty_append_only(session: Session, flush_context, instances) -> None:  # noqa: ARG001
    """before_update only fires for rows with net changes; a dirty-but-unchanged
    row would pass. Check the dirty and deleted sets directly so the refusal
    happens even for a no-op assignment."""
    for obj in list(session.dirty):
        if isinstance(obj, APPEND_ONLY) and session.is_modified(obj, include_collections=False):
            _refuse(None, None, obj)
    for obj in list(session.deleted):
        if isinstance(obj, APPEND_ONLY):
            _refuse(None, None, obj)
