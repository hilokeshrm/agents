"""
state_history as an event stream (WBS 9.2).

Converts Design Status and Stage from columns that get overwritten into an
append-only stream: every transition is a new state_history row, with actor,
timestamp and reason code. A moved card must call record_transition rather than
assigning to opportunity.stage directly -- that is the one behaviour change this
task requires, and it is what makes time in stage, win rate, stall detection and
the calibration table's outcome labels computable from the stream instead of
estimated.

TRANSITION_FIELDS are the only two columns state_history tracks today, matching
the two event types the architecture doc names explicitly (Design Status and Stage).

A reason_code, when given, is validated against the relevant WBS 2.6 vocabulary
(app/registry/reason_codes.py) rather than accepted as free text -- that
enforcement is real even though the vocabularies themselves are still draft/
unratified. It stays optional: those vocabularies aren't signed off yet, so this
does not force a value through an unratified list.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.opportunity import Opportunity
from app.db.models.state_history import StateHistory
from app.registry.reason_codes import LOSS_REASON_CODES, STAGE_EXIT_REASON_CODES

TRANSITION_FIELDS = {"design_status", "stage"}


def _validate_reason_code(field: str, to_value: str, reason_code: str | None) -> None:
    if field == "design_status" and to_value.lower() == "lost" and reason_code is None:
        raise ValueError("a loss_reason code is required when design status becomes Lost")
    if reason_code is None:
        return
    if field == "stage" and not STAGE_EXIT_REASON_CODES.validate(reason_code):
        raise ValueError(
            f"{reason_code!r} is not in the stage_exit_reason vocabulary "
            f"{sorted(STAGE_EXIT_REASON_CODES.codes)}"
        )
    if field == "design_status" and to_value.lower() == "lost" and not LOSS_REASON_CODES.validate(reason_code):
        raise ValueError(
            f"{reason_code!r} is not in the loss_reason vocabulary {sorted(LOSS_REASON_CODES.codes)}"
        )

# Outcome labels a design_status transition can resolve to. Until WBS 2.6 (reason-code
# vocabulary) and 1.1 Q1 (Matrix A ratification) land, these are the only two values
# assumed stable enough to key a win/loss computation on.
WIN_VALUES = {"design win", "mass production"}
LOSS_VALUES = {"lost"}

# Design statuses whose forecast impact is terminal, so a person cannot set them
# on their own: they need the close/Design-Lost grant (manager or director).
# The route enforces it; app/api/v1/registry.py serves it, so a screen labels the
# rule that will actually be applied rather than a copy of it.
APPROVAL_REQUIRED_STATUSES = frozenset({"lost", "mass production"})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware_utc(dt: datetime) -> datetime:
    """Postgres round-trips DateTime(timezone=True) as aware; SQLite (tests, and
    any dev use without a running Postgres) silently drops the tzinfo. Every
    timestamp this service reads is written as UTC, so a naive value is assumed
    to already be UTC rather than left to blow up on subtraction."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def record_transition(
    db: Session,
    opportunity: Opportunity,
    field: str,
    to_value: str,
    actor: str,
    reason_code: str | None = None,
) -> StateHistory:
    """Writes the event and updates the opportunity's current value in the same
    transaction. This is the only sanctioned way to change design_status or stage;
    an UPDATE that bypasses this function leaves no trace of what changed or why."""
    if field not in TRANSITION_FIELDS:
        raise ValueError(f"field must be one of {TRANSITION_FIELDS}, got {field!r}")
    _validate_reason_code(field, to_value, reason_code)

    from_value = getattr(opportunity, field)
    event = StateHistory(
        opportunity_id=opportunity.id,
        field=field,
        from_value=from_value,
        to_value=to_value,
        actor=actor,
        reason_code=reason_code,
    )
    db.add(event)
    setattr(opportunity, field, to_value)
    db.flush()
    try:
        from app.services.scheduler import enqueue_event_run

        enqueue_event_run(opportunity.id)   # decision #46: a change triggers a targeted re-score
    except Exception as exc:  # noqa: BLE001
        print(f"[scheduler] enqueue: {type(exc).__name__}: {exc}")
    try:
        from app.services.webhooks import deliver_event

        deliver_event(db, event="transition.recorded", payload={
            "opportunity_id": opportunity.id, "external_id": opportunity.external_id, "field": field,
            "from": from_value, "to": to_value, "actor": actor, "reason_code": reason_code,
        })
    except Exception as exc:  # noqa: BLE001 -- a delivery failure never undoes a transition
        print(f"[webhooks] transition.recorded: {type(exc).__name__}: {exc}")
    return event


def seed_initial_state(
    db: Session, opportunity: Opportunity, actor: str, reason_code: str | None = None
) -> list[StateHistory]:
    """Called once at intake so an opportunity's first stage and design status are
    also stream events (from_value=None), not just column values with no history.
    reason_code is the loss reason when the row is entered as Lost."""
    events = []
    for field in ("design_status", "stage"):
        event = StateHistory(
            opportunity_id=opportunity.id,
            field=field,
            from_value=None,
            to_value=getattr(opportunity, field),
            actor=actor,
            reason_code=reason_code if field == "design_status" else None,
        )
        db.add(event)
        events.append(event)
    db.flush()
    return events


def time_in_current_stage(db: Session, opportunity: Opportunity) -> timedelta:
    """WBS 9.2 done-when: time in stage computed from the stream, not estimated.
    Falls back to time since the opportunity was created if it has never recorded
    a stage transition (e.g. rows from before this service existed)."""
    stmt = (
        select(StateHistory)
        .where(StateHistory.opportunity_id == opportunity.id, StateHistory.field == "stage")
        .order_by(StateHistory.id.desc())
        .limit(1)
    )
    latest = db.scalars(stmt).first()
    since = latest.occurred_at if latest is not None else opportunity.created_at
    return _now() - _as_aware_utc(since)


@dataclass
class WinRate:
    won: int
    lost: int
    resolved: int
    rate: float | None  # None when nothing has resolved yet, never 0.0 standing in for "unknown"


def win_rate(db: Session, *, owner: str | None = None, region: str | None = None) -> WinRate:
    """WBS 9.2 done-when: win rate computed from the stream, not estimated.

    Resolved = an opportunity whose *latest* design_status transition landed on a
    win or loss value. An opportunity that passed through "Design Win" and later
    moved on is counted by its latest state, not every state it ever visited.
    """
    stmt = select(StateHistory, Opportunity).join(
        Opportunity, StateHistory.opportunity_id == Opportunity.id
    ).where(StateHistory.field == "design_status")
    if owner is not None:
        stmt = stmt.where(Opportunity.owner == owner)
    if region is not None:
        stmt = stmt.where(Opportunity.region == region)

    latest_by_opportunity: dict[str, StateHistory] = {}
    for event, _opp in db.execute(stmt).all():
        current = latest_by_opportunity.get(event.opportunity_id)
        if current is None or event.id > current.id:
            latest_by_opportunity[event.opportunity_id] = event

    won = lost = 0
    for event in latest_by_opportunity.values():
        value = event.to_value.lower()
        if value in WIN_VALUES:
            won += 1
        elif value in LOSS_VALUES:
            lost += 1

    resolved = won + lost
    rate = (won / resolved) if resolved else None
    return WinRate(won=won, lost=lost, resolved=resolved, rate=rate)
