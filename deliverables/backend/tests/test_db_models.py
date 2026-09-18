"""
Schema regression test (WBS 9.1): all ten original tables plus `contact` and
`run` (both added for the UI build, see app/db/models/__init__.py) create cleanly
and the foreign keys resolve end to end. Runs against an in-memory SQLite engine so it needs no
Postgres instance; the Alembic migration chain in alembic/versions/ is the
artifact that actually ships the schema to Postgres.
"""

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import (
    Calibration,
    ConfidenceEvent,
    Contact,
    FieldValue,
    Finding,
    Forecast,
    Opportunity,
    Proposal,
    RubricVersion,
    Snapshot,
    StateHistory,
)
from app.db.models.field_value import TRUST_LEVELS


def _engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


def test_all_fourteen_tables_created():
    engine = _engine()
    assert set(Base.metadata.tables.keys()) == {
        "opportunity",
        "state_history",
        "snapshot",
        "field_value",
        "forecast",
        "contact",
        "proposal",
        "confidence_event",
        "finding",
        "rubric_version",
        "calibration",
        "run",
        "opportunity_sequence",
        "target", "actual", "notification", "app_user", "memory_chunk", "market_programme", "webhook_subscription", "webhook_delivery", "conversation", "auth_account", "auth_session",
            "owner_history",
    }


def test_opportunity_and_dependents_round_trip():
    engine = _engine()
    with Session(engine) as s:
        opp = Opportunity(
            region="Korea", customer="SLM", end_customer="GM", project="Hercules",
            part_number="AX01", design_status="Design Win", stage="PVT",
            eau_kpcs=1100, disty_asp=3, confidence=1.0,
            owner="jdoe", confidence_rationale="locked design win",
        )
        s.add(opp)
        s.flush()

        s.add(StateHistory(opportunity_id=opp.id, field="stage", from_value="DVT", to_value="PVT", actor="jdoe"))
        s.add(FieldValue(
            opportunity_id=opp.id, param="V1", value="1100",
            source="direct_entry", trust=TRUST_LEVELS["direct_entry"],
        ))

        snap = Snapshot(sha256="a" * 64, source_uri="upload://form", row_counts={})
        s.add(snap)
        s.flush()
        s.add(Finding(opportunity_id=opp.id, snapshot_id=snap.id, rule_id="V-a", severity="advisory", message="test"))
        s.add(Forecast(
            opportunity_id=opp.id, snapshot_id=snap.id, year=2026, quarter=1,
            units_kpcs=275, volume_revenue_k=825, phasing_rule="flat",
        ))

        rv = RubricVersion(label="2026.1-draft", matrix_a={}, rubric_factors={}, published_by="system")
        s.add(rv)
        s.flush()
        prop = Proposal(
            opportunity_id=opp.id, rubric_version_id=rv.id,
            base_confidence=1.0, proposed_confidence=1.0, factors=[],
        )
        s.add(prop)
        s.flush()
        s.add(ConfidenceEvent(
            opportunity_id=opp.id, proposal_id=prop.id, rubric_version_id=rv.id,
            event_type="proposal", base_confidence=1.0, resulting_confidence=1.0,
            model_id="mock", actor="jdoe",
        ))
        s.add(Calibration(
            owner="jdoe", region="Korea", bias_pp=-5.0, sample_size=12,
            window_start=date(2025, 1, 1), window_end=date(2025, 12, 31),
        ))
        s.commit()

        got = s.get(Opportunity, opp.id)
        assert len(got.state_events) == 1
        assert len(got.field_values) == 1
        assert len(got.findings) == 1
        assert len(got.forecasts) == 1
        assert len(got.proposals) == 1
        assert len(got.confidence_events) == 1
