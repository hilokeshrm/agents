"""
Regression tests for the provenance wrapper (WBS 3.6).
"""

from datetime import datetime, timezone

import pytest

from app.intake.provenance import wrap_row


def test_wrap_row_cites_param_ids_not_field_names():
    wrapped = wrap_row({"region": "Korea", "stage": "PVT"}, source="direct_entry", trust=4)
    assert wrapped["region"].param == "V1"
    assert wrapped["stage"].param == "V9"


def test_wrap_row_carries_source_trust_and_timestamp():
    at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    wrapped = wrap_row({"region": "Korea"}, source="crm", trust=3, at=at)
    fv = wrapped["region"]
    assert fv.value == "Korea"
    assert fv.source == "crm"
    assert fv.trust == 3
    assert fv.at == at


def test_wrap_row_defaults_timestamp_to_now():
    before = datetime.now(timezone.utc)
    wrapped = wrap_row({"region": "Korea"}, source="direct_entry", trust=4)
    after = datetime.now(timezone.utc)
    assert before <= wrapped["region"].at <= after


def test_wrap_row_covers_every_opportunitycreate_field():
    """The full intake schema, not just the workbook-derived subset -- proves
    FIELD_TO_PARAM_NAME didn't silently drift from OpportunityCreate."""
    from app.schemas.opportunity import OpportunityCreate

    row = {name: "x" for name in OpportunityCreate.model_fields}
    wrapped = wrap_row(row, source="direct_entry", trust=4)
    assert set(wrapped.keys()) == set(OpportunityCreate.model_fields)


def test_wrap_row_raises_on_unregistered_field():
    with pytest.raises(KeyError, match="no ParamSpec mapping"):
        wrap_row({"totally_made_up_field": "x"}, source="direct_entry", trust=4)
