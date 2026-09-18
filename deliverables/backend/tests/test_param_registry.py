"""
Regression tests for the parameter registry (WBS 2.1). Two things are checked
against a real, verifiable claim rather than the WBS document's own "28 live +
26 proposed" estimate, which this registry does not claim to reproduce exactly
(see the module docstring in app/registry/parameters.py for why):

1. Every entry is well-formed (unique id, a real Python type, tab membership
   consistent with present_in_current_file).
2. The registry covers every field app/schemas/opportunity.py's intake schema
   actually reads -- the literal, testable half of WBS 2.1's done-when.
"""

from app.registry.param_spec import ParamRegistry, ParamSpec
from app.registry.parameters import PARAMS
from app.schemas.opportunity import OpportunityCreate

# OpportunityCreate field name -> the ParamSpec name it corresponds to. Field
# names differ slightly in casing/spelling from the document's column names
# (eau_kpcs vs "EAU"), so this is an explicit map, not a fuzzy match.
INTAKE_FIELD_TO_PARAM_NAME = {
    "external_id": "Opportunity ID",
    "region": "Region",
    "customer": "Customer",
    "end_customer": "End Customer",
    "project": "Project Name",
    "application": "Application",
    "product_line": "Product Line",
    "part_number": "Part Number",
    "design_status": "Design Status",
    "stage": "Stage",
    "mp_date": "M/P Date",
    "eau_kpcs": "EAU",
    "unit_set": "Unit/Set",
    "disty_asp": "Disty ASP",
    "resale_asp": "Resale ASP",
    "confidence": "Confidence Level",
    "competitor_part": "Competitor Part#",
    "owner": "Owner",
    "evidence": "Comments",  # closest existing slot; V19, not a dedicated proposed param
    "confidence_rationale": "Confidence Rationale",
    "loss_reason": "Loss Reason Code",
    "phasing_profile": "Quarterly Unit Forecast",  # V23: the programme profile (WBS 5.5)
    "nre_charge_k": "NRE Charge",
}


def test_registry_has_61_well_formed_entries():
    """29 original entries, the 16 FCST quarterly columns individually (V30-V45),
    and 16 proposed platform parameters (targets, actuals, milestones, history,
    competitor and programme data, cost, owner bias) registered absent."""
    assert len(PARAMS) == 61
    ids = {p.id for p in PARAMS.all()}
    assert len(ids) == 61  # register() itself also rejects duplicates; this re-asserts it

    for spec in PARAMS.all():
        assert isinstance(spec.dtype, type)
        if not spec.present_in_current_file:
            assert spec.tabs == (), f"{spec.id} is proposed but still lists tabs: {spec.tabs}"
        if spec.tabs:
            assert spec.present_in_current_file, f"{spec.id} lists tabs but is marked not present"


def test_duplicate_id_is_rejected():
    registry = ParamRegistry()
    registry.register(ParamSpec("X1", "dup", str, None, None, False, (), True))
    try:
        registry.register(ParamSpec("X1", "dup again", str, None, None, False, (), True))
        assert False, "expected ValueError on duplicate id"
    except ValueError:
        pass


def test_registry_covers_every_field_the_intake_schema_reads():
    param_names = {p.name for p in PARAMS.all()}
    for field_name in OpportunityCreate.model_fields:
        expected = INTAKE_FIELD_TO_PARAM_NAME[field_name]  # KeyError = an intake field with no registry entry at all
        assert expected in param_names, f"intake field {field_name!r} maps to unregistered param {expected!r}"


def test_proposed_parameters_are_exactly_the_direct_entry_additions():
    """V25-V29: fields the platform needs that no workbook tab carries -- the
    "registered as absent, not missing" half of WBS 2.1's done-when. V29 (NRE
    Charge) is proposed for a specific reason: the workbook carries NRE only as
    whole FCST_Revenue rows, never as a per-opportunity field."""
    proposed_ids = {p.id for p in PARAMS.proposed()}
    assert {"V25", "V26", "V27", "V28", "V29"} <= proposed_ids
    # Every proposed platform parameter names what an analysis is waiting on.
    assert {"G1", "G2", "A1", "A2", "A3", "H1", "H2", "H3", "R1", "P1", "P2", "C1", "O1"} <= proposed_ids
    for spec in PARAMS.proposed():
        assert spec.tabs == ()


def test_stage_is_projecttrack_only():
    """The one identity fact most likely to regress silently: Funnel, Mass
    Production and Design Lost have no Stage column at all."""
    stage = PARAMS.get("V9")
    assert stage.tabs == ("ProjectTrack",)
