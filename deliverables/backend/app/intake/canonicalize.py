"""
Canonicalisation (WBS 3.4): applies the enum maps from app/registry/enums.py
(WBS 2.2) to a raw intake row. KR becomes Korea, MOBIS and Mobis both become
Mobis, D-IN becomes Design In, M/P becomes Mass Production.

An unmapped value is a finding, never a new category invented at read time: if
canonicalize_region() returns None for a value on nobody's list (see
app/registry/enums.py), this module does not fall back to using the raw string
as a region. The field is left out of `canonical`
and a Finding explains why, so a roll-up that groups by canonical region neither
silently drops that row nor invents a fourth region nobody asked for.

This is the normalisation layer (package 3.0) applying rules the registry layer
(package 2.0) defines -- deliberately two different modules, so a rule change
(what "KR" maps to) never requires touching how rows get walked.
"""

from dataclasses import dataclass, field

from app.registry.enums import (
    canonicalize_customer,
    canonicalize_design_status,
    canonicalize_region,
    canonicalize_stage,
)

# Row key -> (canonicalizer, output key). Fields with no closed enum (Application,
# Product Line, Part Number, ...) are not listed here and pass through untouched --
# WBS 2.2 only names Region, Design Status, Stage, Customer as closed/normalized.
_ENUM_FIELDS: dict[str, tuple] = {
    "region": (canonicalize_region, "region"),
    "design_status": (canonicalize_design_status, "design_status"),
    "stage": (canonicalize_stage, "stage"),
}

PASSTHROUGH_FIELDS = (
    "phasing_profile",
    "external_id", "end_customer", "project", "part_number", "application", "product_line", "mp_date",
    "eau_kpcs", "unit_set", "disty_asp", "resale_asp", "confidence", "competitor_part", "comments",
    "nre_charge_k",
    # Direct-entry-only fields (V25-V27 in app/registry/parameters.py): no workbook
    # tab carries these, so there is no canonical mapping to apply -- they pass
    # through the same as any other field with no closed enum.
    "owner", "evidence", "confidence_rationale",
)


@dataclass(frozen=True)
class Finding:
    field: str
    raw_value: str
    message: str


@dataclass
class CanonicalizationResult:
    canonical: dict = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)


def canonicalize_row(raw_row: dict) -> CanonicalizationResult:
    result = CanonicalizationResult()

    for row_key, (canonicalizer, out_key) in _ENUM_FIELDS.items():
        if row_key not in raw_row or raw_row[row_key] is None:
            continue
        raw_value = raw_row[row_key]
        canonical_value = canonicalizer(raw_value)
        if canonical_value is None:
            result.findings.append(Finding(
                field=row_key, raw_value=raw_value,
                message=f"{row_key} value {raw_value!r} has no canonical mapping -- not applied, not invented",
            ))
        else:
            result.canonical[out_key] = canonical_value

    if "customer" in raw_row and raw_row["customer"] is not None:
        # Customer is an open-set normalizer (WBS 2.2), not a closed enum -- it
        # always succeeds, so it never produces a finding.
        result.canonical["customer"] = canonicalize_customer(raw_row["customer"])

    for key in PASSTHROUGH_FIELDS:
        if key in raw_row:
            result.canonical[key] = raw_row[key]

    return result
