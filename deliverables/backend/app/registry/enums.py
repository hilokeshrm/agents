"""
Canonical enums (WBS 2.2). Sourced from the "Values in the file -> Canonical
form" table in
docs/03-reference/Opportunity_Tracking_Agent_Tab_and_Field_Map.docx, not invented.

The contract every canonicalize_* function follows, per that document and WBS 3.4:
an unmapped value returns None -- it becomes a finding once WBS 4.0 (the
validation engine) exists, never a silently invented new category. Where the
source document left a mapping open, the value adopted is the one recorded in
the decision register (docs/OT_Decision_Register_and_Claude_API_Purpose.md) and
is marked provisional there, not silently chosen here.

Region and Design Status are closed enums (fixed value sets, matching V1/V8 in
app/registry/parameters.py). Customer is not an enum at all -- it is an open set
that only needs case-insensitive de-duplication, which is why it gets a
normalizer instead of a fixed map.
"""

# Region (V1). David Nam's canonical list is Europe, Taiwan, Japan, Korea,
# India, US and Other. "North America" was left unmapped while the question was
# open; it is now mapped to US as a PROVISIONAL decision recorded in
# docs/OT_Decision_Register_and_Claude_API_Purpose.md ("Provisional additions",
# 2026-09-15) -- the file has no Canadian or Mexican rows to argue otherwise,
# and "Other" would hide a real US opportunity under a catch-all. Change the
# register first if this ever changes, then this map.
REGION_MAP: dict[str, str] = {
    "kr": "Korea",
    "korea": "Korea",
    "eu": "Europe",
    "europe": "Europe",
    "taiwan": "Taiwan",
    "japan": "Japan",
    "india": "India",
    "us": "US",
    "usa": "US",
    "north america": "US",
    "other": "Other",
}


def canonicalize_region(raw: str) -> str | None:
    return REGION_MAP.get(raw.strip().lower())


# Design Status (V8). NRE and TBD are excluded on purpose: the source document is
# explicit that "NRE and TBD are not statuses and need their own handling" -- NRE
# becomes its own record type (WBS 3.5), TBD becomes null (WBS 3.3), and neither
# should silently canonicalize into a design-status value.
DESIGN_STATUS_MAP: dict[str, str] = {
    "m/p": "Mass Production",
    "mass production": "Mass Production",
    "d-in": "Design In",
    "design in": "Design In",
    "design win": "Design Win",
    "sample": "Sample",
    "promotion": "Promotion",
    "evaluation": "Evaluation",
    "lost": "Lost",
}

NOT_A_DESIGN_STATUS = frozenset({"nre", "tbd"})


def canonicalize_design_status(raw: str) -> str | None:
    key = raw.strip().lower()
    if key in NOT_A_DESIGN_STATUS:
        return None
    return DESIGN_STATUS_MAP.get(key)


# Customer (V2): open set, case-insensitive match, one canonical spelling per
# account -- not a closed enum like Region or Design Status. Seed with the
# accounts named in the source document; an unseen name is still valid, it just
# is not pre-canonicalized to a particular casing yet.
CUSTOMER_CANON: dict[str, str] = {
    "mobis": "Mobis",
    "slm": "SLM",
    "flextron": "Flextron",
    "ode": "ODE",
    "foxc": "Foxc",
}


def canonicalize_customer(raw: str) -> str:
    key = raw.strip().lower()
    return CUSTOMER_CANON.get(key, raw.strip())


# Stage (V9): the four values in the file are already mutually consistent, no
# variant table exists in the source document for this one -- registered as a
# closed enum (matching V9) all the same, since app/registry/parameters.py and
# WBS 2.2 both name it as one of the six enums this task builds.
STAGE_VALUES: tuple[str, ...] = ("Concept", "EVT", "DVT", "PVT")


def canonicalize_stage(raw: str) -> str | None:
    key = raw.strip()
    for value in STAGE_VALUES:
        if key.lower() == value.lower():
            return value
    return None
