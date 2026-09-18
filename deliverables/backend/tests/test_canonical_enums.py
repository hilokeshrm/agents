"""
Regression tests for canonical enums (WBS 2.2), against the raw variants
documented in Opportunity_Tracking_Agent_Tab_and_Field_Map.docx and the values
actually present in tests/fixtures/sample_pipeline.json.
"""

import json
from pathlib import Path

from app.registry.enums import (
    canonicalize_customer,
    canonicalize_design_status,
    canonicalize_region,
    canonicalize_stage,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sample_pipeline.json"


def test_region_variants_from_the_source_document():
    assert canonicalize_region("KR") == "Korea"
    assert canonicalize_region("Korea") == "Korea"
    assert canonicalize_region("EU") == "Europe"
    assert canonicalize_region("Taiwan") == "Taiwan"
    assert canonicalize_region("Japan") == "Japan"


def test_region_case_and_whitespace_insensitive():
    assert canonicalize_region("  korea  ") == "Korea"
    assert canonicalize_region("kr") == "Korea"


def test_north_america_maps_to_us_per_the_decision_register():
    """The source document left this open ("Confirm whether North America
    becomes US"). David Nam did not answer, so the decision register adopted
    US provisionally (2026-09-15). A value that is genuinely on nobody's list
    still reports unmapped (None) so a caller can raise it as a finding."""
    assert canonicalize_region("North America") == "US"
    assert canonicalize_region("USA") == "US"
    assert canonicalize_region("Other") == "Other"
    assert canonicalize_region("LATAM") is None


def test_design_status_variants_from_the_source_document():
    assert canonicalize_design_status("M/P") == "Mass Production"
    assert canonicalize_design_status("D-IN") == "Design In"
    assert canonicalize_design_status("Design Win") == "Design Win"
    assert canonicalize_design_status("Mass Production") == "Mass Production"


def test_nre_and_tbd_are_not_design_statuses():
    assert canonicalize_design_status("NRE") is None
    assert canonicalize_design_status("TBD") is None
    assert canonicalize_design_status("tbd") is None


def test_unmapped_design_status_returns_none_not_a_guess():
    assert canonicalize_design_status("Something Nobody Wrote Down") is None


def test_customer_case_insensitive_dedup():
    assert canonicalize_customer("MOBIS") == "Mobis"
    assert canonicalize_customer("Mobis") == "Mobis"
    assert canonicalize_customer("mobis") == "Mobis"


def test_customer_unseen_account_is_not_rejected():
    """Customer is an open set (WBS 2.2: 'case-insensitive match, one canonical
    spelling per account'), not a closed enum -- an unseen name still passes
    through, just without pre-canonicalized casing."""
    assert canonicalize_customer("Brand New Account") == "Brand New Account"


def test_stage_canonicalizes_case():
    assert canonicalize_stage("pvt") == "PVT"
    assert canonicalize_stage("Concept") == "Concept"


def test_stage_unmapped_returns_none():
    assert canonicalize_stage("Prototype") is None


def test_fixture_region_and_design_status_values_all_canonicalize():
    data = json.loads(FIXTURE.read_text())
    for row in data["project_track"]:
        assert canonicalize_region(row["region"]) is not None, row["region"]
        assert canonicalize_design_status(row["design_status"]) is not None, row["design_status"]
        assert canonicalize_stage(row["stage"]) is not None, row["stage"]
