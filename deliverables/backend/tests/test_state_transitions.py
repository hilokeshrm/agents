"""
Regression tests for the state_history event stream (WBS 9.2). Covers the
done-when criteria directly: a moved card writes an event rather than an update,
and time in stage / win rate are computed from the stream, not estimated.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models.opportunity import Opportunity
from app.db.models.state_history import StateHistory
from app.services.state_transitions import (
    record_transition,
    seed_initial_state,
    time_in_current_stage,
    win_rate,
)


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _make_opportunity(**overrides) -> Opportunity:
    defaults = dict(
        region="Korea", customer="SLM", end_customer="GM", project="Hercules",
        part_number="AX01", design_status="Evaluation", stage="EVT",
        eau_kpcs=1100, disty_asp=3, confidence=0.5,
        owner="jdoe", confidence_rationale="under evaluation",
    )
    defaults.update(overrides)
    return Opportunity(**defaults)


def test_seed_initial_state_writes_from_none(session):
    opp = _make_opportunity()
    session.add(opp)
    session.flush()

    events = seed_initial_state(session, opp, actor="jdoe")
    session.commit()

    assert {e.field for e in events} == {"design_status", "stage"}
    assert all(e.from_value is None for e in events)
    assert {e.to_value for e in events} == {"Evaluation", "EVT"}


def test_record_transition_updates_opportunity_and_writes_event(session):
    opp = _make_opportunity()
    session.add(opp)
    session.flush()
    seed_initial_state(session, opp, actor="jdoe")

    event = record_transition(
        session, opp, field="stage", to_value="DVT", actor="jdoe", reason_code="advanced_to_next_stage"
    )
    session.commit()

    assert opp.stage == "DVT"
    assert event.from_value == "EVT"
    assert event.to_value == "DVT"
    assert event.reason_code == "advanced_to_next_stage"

    all_events = session.query(StateHistory).filter_by(opportunity_id=opp.id, field="stage").all()
    assert len(all_events) == 2  # seed + this transition


def test_record_transition_rejects_unknown_field(session):
    opp = _make_opportunity()
    session.add(opp)
    session.flush()

    with pytest.raises(ValueError):
        record_transition(session, opp, field="eau_kpcs", to_value="9999", actor="jdoe")


def test_record_transition_rejects_reason_code_outside_stage_exit_vocabulary(session):
    opp = _make_opportunity()
    session.add(opp)
    session.flush()

    with pytest.raises(ValueError, match="stage_exit_reason"):
        record_transition(session, opp, field="stage", to_value="DVT", actor="jdoe", reason_code="just because")


def test_record_transition_rejects_reason_code_outside_loss_vocabulary_only_when_losing(session):
    opp = _make_opportunity()
    session.add(opp)
    session.flush()

    # Not a "Lost" transition -- the loss vocabulary does not apply, so an
    # otherwise-unvalidated design_status reason code is accepted as-is today.
    record_transition(session, opp, field="design_status", to_value="Design In", actor="jdoe", reason_code="anything")

    with pytest.raises(ValueError, match="loss_reason"):
        record_transition(session, opp, field="design_status", to_value="Lost", actor="jdoe", reason_code="just because")

    # A real loss_reason code is accepted.
    event = record_transition(session, opp, field="design_status", to_value="Lost", actor="jdoe", reason_code="price")
    assert event.reason_code == "price"


def test_time_in_current_stage_reflects_latest_transition(session):
    opp = _make_opportunity()
    session.add(opp)
    session.flush()
    seed_initial_state(session, opp, actor="jdoe")
    session.commit()

    just_after_seed = time_in_current_stage(session, opp)
    assert just_after_seed < timedelta(seconds=5)

    # Backdate the seed event to simulate the opportunity having sat in EVT for
    # 10 days. state_history is append-only (WBS 8.2): mutating the row through
    # the ORM is refused, so the test goes through a Core statement -- the one
    # path the ORM guard documents as out of its reach.
    import pytest
    from sqlalchemy import update

    from app.db.immutable import ImmutableRowError

    stage_event = session.query(StateHistory).filter_by(opportunity_id=opp.id, field="stage").one()
    stage_event.occurred_at = datetime.now(timezone.utc) - timedelta(days=10)
    with pytest.raises(ImmutableRowError):
        session.flush()
    session.rollback()
    session.execute(
        update(StateHistory)
        .where(StateHistory.opportunity_id == opp.id, StateHistory.field == "stage")
        .values(occurred_at=datetime.now(timezone.utc) - timedelta(days=10))
    )
    session.commit()

    aged = time_in_current_stage(session, opp)
    assert timedelta(days=9, hours=23) < aged < timedelta(days=10, hours=1)

    # A new transition resets the clock.
    record_transition(session, opp, field="stage", to_value="DVT", actor="jdoe")
    session.commit()
    reset = time_in_current_stage(session, opp)
    assert reset < timedelta(seconds=5)


def test_win_rate_counts_latest_state_only(session):
    won = _make_opportunity(project="Hercules", owner="alice", region="Korea", design_status="Evaluation")
    lost = _make_opportunity(project="Poseidon", owner="alice", region="Korea", design_status="Evaluation")
    open_ = _make_opportunity(project="Apollo", owner="bob", region="EU", design_status="Evaluation")
    session.add_all([won, lost, open_])
    session.flush()
    for opp in (won, lost, open_):
        seed_initial_state(session, opp, actor=opp.owner)

    # Won opportunity churns through a couple of states before landing on Design Win.
    record_transition(session, won, field="design_status", to_value="Design In", actor="alice")
    record_transition(session, won, field="design_status", to_value="Design Win", actor="alice")
    record_transition(session, lost, field="design_status", to_value="Lost", actor="alice", reason_code="price")
    # open_ stays at "Evaluation" -- unresolved, must not count as a loss.
    session.commit()

    overall = win_rate(session)
    assert overall.won == 1
    assert overall.lost == 1
    assert overall.resolved == 2
    assert overall.rate == pytest.approx(0.5)

    alice_only = win_rate(session, owner="alice")
    assert alice_only.won == 1
    assert alice_only.lost == 1

    bob_only = win_rate(session, owner="bob")
    assert bob_only.resolved == 0
    assert bob_only.rate is None
