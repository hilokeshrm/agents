"""
Provenance wrapper (WBS 3.6): FieldValue(param, value, source, at, trust) on every
value, from every path (docs/02-architecture/OppTrack_Complete_Architecture.html,
section 10 -- the frozen contract this module implements). This is what the
Opportunities list renders as source badges, what the connector precedence ladder
arbitrates over, and what lets a reviewer answer "who put that there" without
opening a log.

wrap_row operates on an already-canonicalized row (app/intake/canonicalize.py,
WBS 3.4) and cites the ParamSpec id (app/registry/parameters.py, WBS 2.1) for
every field, never the field's own name -- matching the registry's own rule that
nothing downstream may reference a column name.

An intake field with no corresponding registry entry raises rather than being
silently skipped: WBS 3.6's done-when is "no value reaches the calc engine
without a source and a trust level attached," which a silent skip would quietly
violate the moment someone added a field to the intake schema and forgot the
registry.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from app.registry.param_spec import ParamRegistry
from app.registry.parameters import PARAMS

# Intake row key -> the ParamSpec name it corresponds to (app/registry/parameters.py).
# "evidence" has no dedicated proposed parameter; it shares Comments (V19), the
# closest existing slot -- same choice tests/test_param_registry.py already makes
# for registry-coverage purposes.
FIELD_TO_PARAM_NAME: dict[str, str] = {
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
    "nre_charge_k": "NRE Charge",
    "resale_asp": "Resale ASP",
    "confidence": "Confidence Level",
    "competitor_part": "Competitor Part#",
    "owner": "Owner",
    "evidence": "Comments",
    "confidence_rationale": "Confidence Rationale",
    "loss_reason": "Loss Reason Code",
    "phasing_profile": "Quarterly Unit Forecast",
    "application": "Application",
    "product_line": "Product Line",
    "comments": "Comments",
}


@dataclass(frozen=True)
class FieldValue:
    param: str  # ParamSpec id, e.g. "V1" -- never the row key
    value: object
    source: str
    at: datetime
    trust: int


def wrap_row(
    row: dict,
    source: str,
    trust: int,
    registry: ParamRegistry = PARAMS,
    at: datetime | None = None,
) -> dict[str, FieldValue]:
    """Wraps every value in an already-canonicalized row. Keys of the returned
    dict are the original intake field names (convenient for callers), values
    carry the ParamSpec id -- so a FieldValue is self-describing even out of
    context, but a caller iterating the wrapper still has a familiar key."""
    at = at or datetime.now(timezone.utc)
    wrapped: dict[str, FieldValue] = {}
    for key, value in row.items():
        if key not in FIELD_TO_PARAM_NAME:
            raise KeyError(
                f"intake field {key!r} has no ParamSpec mapping in FIELD_TO_PARAM_NAME -- "
                "register it in app/registry/parameters.py and add it here before it can "
                "reach the calc engine with provenance attached"
            )
        param_name = FIELD_TO_PARAM_NAME[key]
        spec = registry.by_name(param_name)
        wrapped[key] = FieldValue(param=spec.id, value=value, source=source, at=at, trust=trust)
    return wrapped
