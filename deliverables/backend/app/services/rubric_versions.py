"""
Matrix A and the factor rubric as published versions (WBS 2.3, 7.1) -- the
mechanism behind the Rubric & Matrix A admin screen (WBS 10.7).

Editing produces a draft the caller holds; publishing writes a rubric_version
row and stamps its id on every proposal and confidence_event produced afterwards.
That is the whole point: two runs can then be compared rather than argued about,
and a cap change is a policy change with a version behind it rather than a
number quietly tuned until the model agrees with you. Publishing re-runs nothing;
existing proposals keep the version that produced them.

What is real here and what is not, precisely:

- REAL: the versioning, the stamping, and the enforcement that a run must have a
  published version to score against.
- The v1 contents are the decision register's provisional answers
  (docs/OT_Decision_Register_and_Claude_API_Purpose.md, adopted 2026-09-15
  after David Nam did not reply): Matrix A baselines, a 0.95 ceiling, a 15pp
  factor cap, a 20pp run cap, lifecycle bands derived from the baselines, and
  a gate_all review policy. publish_v1() publishes exactly that, once.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.rubric_version import RubricVersion
from app.judgment.matrix_b import RULES
from app.registry.enums import DESIGN_STATUS_MAP, STAGE_VALUES

# Canonical design statuses, de-duplicated from the variant map (both "m/p" and
# "mass production" canonicalize to one value; the grid wants one column per
# canonical value, not one per spelling).
DESIGN_STATUSES: tuple[str, ...] = tuple(dict.fromkeys(DESIGN_STATUS_MAP.values()))

CELL_SEP = "|"

MATRIX_A_DEFAULTS: dict[tuple[str, str], float] = {
    ("Promotion", "Concept"): 0.10,
    ("Promotion", "EVT"): 0.15,
    ("Sample", "Concept"): 0.20,
    ("Sample", "EVT"): 0.30,
    ("Evaluation", "Concept"): 0.20,
    ("Evaluation", "EVT"): 0.35,
    ("Design In", "DVT"): 0.65,
    ("Design In", "PVT"): 0.80,
    ("Design Win", "PVT"): 0.90,
    ("Mass Production", "PVT"): 0.95,
}


def cell_key(design_status: str, stage: str) -> str:
    return f"{design_status}{CELL_SEP}{stage}"


def matrix_a_template() -> dict:
    """The recommended Matrix A v1 draft with explicit forbidden pairings."""
    cells = {}
    for status in DESIGN_STATUSES:
        for stage in STAGE_VALUES:
            baseline = MATRIX_A_DEFAULTS.get((status, stage))
            cells[cell_key(status, stage)] = {
                "baseline": baseline,
                "allowed": baseline is not None,
            }

    for stage in STAGE_VALUES:
        cells[cell_key("Lost", stage)] = {"baseline": 0.0, "allowed": True}

    return {
        "cells": cells,
        "design_statuses": list(DESIGN_STATUSES),
        "stages": list(STAGE_VALUES),
    }


# Lifecycle bands, derived from the Matrix A baselines: a proposal that moves a
# row past the baseline of an adjacent band must reach a person (build spec,
# section 06, "Band crossing"). Half-open [min, max). The boundaries are the
# DVT Design In baseline, the PVT Design Win baseline and the Mass Production
# baseline -- so Apollo 0.50 -> 0.66 crosses into Design In and queues, exactly
# the specification's worked example.
LIFECYCLE_BANDS_V1: list[dict] = [
    {"label": "early", "min": None, "max": 0.65},
    {"label": "design_in", "min": 0.65, "max": 0.90},
    {"label": "design_win", "min": 0.90, "max": 0.95},
    {"label": "mass_production", "min": 0.95, "max": None},
]

# Decision #21: the agent proposes, a human resolves. "gate_all" queues every
# proposal. "gate_band_crossing" is Plate 2's step 9 -- a proposal that crosses
# no band applies on its own -- and is a published policy change, not a code
# change, if the business ever wants it.
REVIEW_POLICIES = ("gate_all", "gate_band_crossing")
REVIEW_POLICY_V1 = "gate_all"

RUBRIC_V1_LABEL = "2026.1"
RUBRIC_V1_SOURCE = "decision-register-v1"


def rubric_template() -> dict:
    """The Matrix B factor list with each rule's own cap, the v1 bounds
    (decision register section 3), the lifecycle bands and the review policy."""
    return {
        "factors": [
            {
                "rule_id": r.id, "key": r.key, "label": f"{r.id} {r.label}", "guidance": r.guidance,
                "direction": r.direction, "cap_pp": r.cap_pp, "requires": list(r.requires),
                "availability": r.availability, "enabled": True,
            }
            for r in RULES
        ],
        "caps": {
            "factor_cap_pp": 15.0,
            "run_cap_pp": 20.0,
            "confidence_ceiling": 0.95,
            "confidence_floor": 0.05,
        },
        "lifecycle_bands": [dict(b) for b in LIFECYCLE_BANDS_V1],
        "review_policy": REVIEW_POLICY_V1,
        "source": RUBRIC_V1_SOURCE,
    }


@dataclass(frozen=True)
class Caps:
    factor_cap_pp: float | None
    confidence_ceiling: float | None
    confidence_floor: float | None
    run_cap_pp: float | None = None


def caps_of(version: RubricVersion) -> Caps:
    raw = (version.rubric_factors or {}).get("caps") or {}
    return Caps(
        factor_cap_pp=raw.get("factor_cap_pp"),
        confidence_ceiling=raw.get("confidence_ceiling"),
        confidence_floor=raw.get("confidence_floor"),
        run_cap_pp=raw.get("run_cap_pp"),
    )


def factor_caps_of(version: RubricVersion) -> dict[str, float]:
    """Per-factor caps a version publishes (key -> pp). Matrix B's own cap
    still applies underneath: a version may lower a cap, never raise one."""
    factors = (version.rubric_factors or {}).get("factors") or []
    return {f["key"]: float(f["cap_pp"]) for f in factors if f.get("cap_pp") is not None}


def review_policy_of(version: RubricVersion) -> str:
    policy = (version.rubric_factors or {}).get("review_policy") or REVIEW_POLICY_V1
    return policy if policy in REVIEW_POLICIES else REVIEW_POLICY_V1


def enabled_factor_keys(version: RubricVersion) -> set[str]:
    factors = (version.rubric_factors or {}).get("factors") or []
    return {f["key"] for f in factors if f.get("enabled", True)}


def baseline_for(version: RubricVersion, design_status: str, stage: str) -> float | None:
    """The Matrix A baseline confidence for a pairing, or None when the cell is
    unset. None is not 0.0 and is not "no baseline exists in principle" -- it is
    "nobody has ratified this cell", which is why every caller renders it as a
    dash rather than folding it into a comparison."""
    cell = (version.matrix_a or {}).get("cells", {}).get(cell_key(design_status, stage))
    return None if cell is None else cell.get("baseline")


def is_forbidden(version: RubricVersion, design_status: str, stage: str) -> bool:
    cell = (version.matrix_a or {}).get("cells", {}).get(cell_key(design_status, stage))
    return bool(cell) and cell.get("allowed") is False


def publish_v1(db: Session, *, published_by: str = "decision-register") -> RubricVersion:
    """Publishes the v1 rubric from the templates -- Matrix A per the decision
    register (section 2), Matrix B with its caps, the bounds, the bands and the
    gate_all policy. Idempotent on the label: an existing version with that
    label is returned rather than duplicated."""
    for v in list_versions(db):
        if (v.rubric_factors or {}).get("source") == RUBRIC_V1_SOURCE:
            return v
    # A version published from the older six-factor template may already hold
    # the label; the register's rubric then takes the next free suffix.
    taken = {v.label for v in list_versions(db)}
    label = RUBRIC_V1_LABEL
    n = 1
    while label in taken:
        n += 1
        label = f"{RUBRIC_V1_LABEL}-r{n}"
    return publish(
        db, label=label, matrix_a=matrix_a_template(),
        rubric_factors=rubric_template(), published_by=published_by,
    )


def publish(
    db: Session, *, label: str, matrix_a: dict, rubric_factors: dict, published_by: str
) -> RubricVersion:
    version = RubricVersion(
        label=label,
        matrix_a=matrix_a,
        rubric_factors=rubric_factors,
        published_by=published_by,
        published_at=datetime.now(timezone.utc),
    )
    db.add(version)
    db.flush()
    return version


def list_versions(db: Session) -> list[RubricVersion]:
    return list(db.scalars(select(RubricVersion).order_by(RubricVersion.published_at.desc())).all())


TEMPLATE_LABEL = "template (unpublished)"


def template_version() -> RubricVersion:
    """A transient, unsaved RubricVersion built from the v1 templates. Used by
    the intake paths (WBS 4.3) so the Matrix A pairing check runs identically
    whether or not an admin has published yet: the check is a table lookup,
    and the table exists from the moment the decision register does. Never
    stamped on a proposal -- a run still requires a published version."""
    return RubricVersion(
        id="template", label=TEMPLATE_LABEL, matrix_a=matrix_a_template(),
        rubric_factors=rubric_template(), published_by="decision-register",
    )


def effective_version(db: Session) -> RubricVersion:
    """The published version, or the template when none is published."""
    return current_version(db) or template_version()


def current_version(db: Session) -> RubricVersion | None:
    """The most recently published version. None when nothing has been published
    -- callers must handle that rather than fall back to the in-code RUBRIC,
    since an unversioned proposal is exactly what this table exists to prevent."""
    return db.scalars(
        select(RubricVersion).order_by(RubricVersion.published_at.desc(), RubricVersion.id).limit(1)
    ).first()
