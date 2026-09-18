"""
The one canonical intake schema (WBS 1.5, decisions #58, #59, #62, #90).

Direct entry, workbook import, CRM sync and API writes all resolve to this
shape. It is the agreed field list between the service and the form -- the
thing WBS 1.5 asked Lokesh and Dimple to settle -- written as data so the
form, the import mapper, the connectors and the provenance wrapper read one
list rather than four drifting copies.

Three tiers, per decision #62:

- REQUIRED_FOR_CALC: without these Sales Revenue cannot be computed. Missing
  one is BLOCKING: the row is refused at direct entry and withheld at import.
- REQUIRED: the register's required list. Missing one at intake is an
  ADVISORY finding on the row and fires J-12 in the judgment layer; the row
  is accepted so a real opportunity is never lost to a blank Application.
- OPTIONAL: present when known.

Every entry cites its ParamSpec id so provenance is written by id.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class IntakeField:
    name: str
    param: str
    tier: str          # "calc" | "required" | "optional"
    label: str
    hint: str = ""


CALC, REQUIRED, OPTIONAL = "calc", "required", "optional"

INTAKE_FIELDS: tuple[IntakeField, ...] = (
    IntakeField("external_id", "V28", OPTIONAL, "Opportunity ID", "Supplied by a CRM or workbook crosswalk; minted as OPP-000001 otherwise"),
    IntakeField("region", "V1", CALC, "Region", "Europe, Taiwan, Japan, Korea, India, US, Other"),
    IntakeField("customer", "V2", CALC, "Customer", "The account the part is sold to"),
    IntakeField("end_customer", "V3", REQUIRED, "End customer", "The OEM behind the account"),
    IntakeField("project", "V4", CALC, "Project", "The opportunity's name"),
    IntakeField("application", "V5", REQUIRED, "Application"),
    IntakeField("product_line", "V6", REQUIRED, "Product line"),
    IntakeField("part_number", "V7", CALC, "Part number", "Supply key across sockets"),
    IntakeField("design_status", "V8", CALC, "Design status"),
    IntakeField("stage", "V9", CALC, "Stage", "Concept, EVT, DVT, PVT"),
    IntakeField("mp_date", "V10", OPTIONAL, "M/P date", "Mass-production start"),
    IntakeField("eau_kpcs", "V11", CALC, "EAU (Kpcs)", "Annual usage in thousands of chips"),
    IntakeField("unit_set", "V12", OPTIONAL, "Unit / set", "Chips per vehicle set -- an attach rate, not a multiplier"),
    IntakeField("disty_asp", "V13", CALC, "Distributor ASP (USD)"),
    IntakeField("resale_asp", "V14", OPTIONAL, "Resale ASP (USD)"),
    IntakeField("nre_charge_k", "V29", OPTIONAL, "NRE charge (USD K)", "One-off engineering or licence, never phased like silicon"),
    IntakeField("confidence", "V17", CALC, "Confidence", "0-1; the one field the agent may propose a change to"),
    IntakeField("competitor_part", "V16", OPTIONAL, "Competitor part"),
    IntakeField("owner", "V26", REQUIRED, "Owner", "The accountable person; decision #5"),
    IntakeField("evidence", "V19", OPTIONAL, "Evidence", "Free text the judgment layer may quote"),
    IntakeField("confidence_rationale", "V27", REQUIRED, "Confidence rationale", "Why the entered confidence is what it is"),
)

BY_NAME: dict[str, IntakeField] = {f.name: f for f in INTAKE_FIELDS}
CALC_FIELDS = tuple(f.name for f in INTAKE_FIELDS if f.tier == CALC)
REQUIRED_FIELDS = tuple(f.name for f in INTAKE_FIELDS if f.tier == REQUIRED)
OPTIONAL_FIELDS = tuple(f.name for f in INTAKE_FIELDS if f.tier == OPTIONAL)

_PLACEHOLDERS = frozenset({"", "tbd", "n/a", "na", "unassigned", "none"})


def is_blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and value.strip().lower() in _PLACEHOLDERS)


def missing(values: dict, tier: str) -> list[str]:
    names = CALC_FIELDS if tier == CALC else REQUIRED_FIELDS if tier == REQUIRED else OPTIONAL_FIELDS
    return [n for n in names if is_blank(values.get(n))]


def describe() -> list[dict]:
    """The schema as the form and the docs render it."""
    return [
        {"name": f.name, "param": f.param, "tier": f.tier, "label": f.label, "hint": f.hint}
        for f in INTAKE_FIELDS
    ]
