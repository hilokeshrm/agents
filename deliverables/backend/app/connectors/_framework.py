"""
Connector framework (WBS 11.1) and the precedence ladder with its
reconciliation queue (WBS 11.2).

A connector declares three things -- SUPPLIES (ParamSpec ids it can fill),
TRUST (its rung on decision #63's ladder) and CADENCE (how often it is pulled)
-- and turns one pull into a list of Observations: (which row, which field,
what value, when, from what reference). The framework does the rest,
identically for every connector:

1. Match the observation to a row: external id first, then the business
   identity (region, customer, project, part).
2. Write a provenanced FieldValue for it, always, so the value is on record
   even when it does not win.
3. Compare with the row's current value and the trust of the value already
   there. Higher trust wins and is applied; equal or lower trust does not
   overwrite -- it raises a reconciliation item through the same queue a
   confidence proposal goes through (Proposal kind="reconciliation"), and a
   person decides.
4. Lifecycle fields (design status, stage) and confidence are never applied
   by a connector at any trust: a stale CRM stage is a question, not a write.

Provenance is what makes automation safe to switch on incrementally: a
connector can be pulled in dry-run mode for a fortnight -- observations and
conflicts recorded, nothing applied -- before it is allowed to write.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.field_value import TRUST_LEVELS
from app.db.models.field_value import FieldValue as FieldValueRow
from app.db.models.opportunity import Opportunity
from app.db.models.proposal import Proposal
from app.intake.provenance import FIELD_TO_PARAM_NAME
from app.registry.parameters import PARAMS

# Fields a connector may set on the row when it out-ranks the current value.
APPLICABLE_FIELDS = frozenset({
    "end_customer", "application", "product_line", "mp_date", "eau_kpcs", "unit_set",
    "disty_asp", "resale_asp", "competitor_part", "owner", "phasing_profile",
})
# Never applied by a connector; always a reconciliation item.
GATED_FIELDS = frozenset({"design_status", "stage", "confidence"})


@dataclass(frozen=True)
class Observation:
    field: str
    value: object
    observed_at: datetime
    ref: str                              # file name, record id, batch
    external_id: str | None = None
    identity: tuple | None = None         # (region, customer, project, part_number)


@dataclass(frozen=True)
class ConnectorSpec:
    name: str
    label: str
    supplies: frozenset                   # ParamSpec ids
    trust: int
    cadence: str                          # "nightly" | "monthly" | "on demand"
    source: str                           # FieldValue.source value
    description: str = ""


class Connector(Protocol):
    spec: ConnectorSpec

    def pull(self, content: bytes, *, ref: str) -> list[Observation]: ...


@dataclass
class PullResult:
    connector: str
    ref: str
    observations: int
    matched: int
    unmatched: int
    applied: int
    reconciliation_items: int
    unchanged: int
    dry_run: bool
    details: list[dict] = field(default_factory=list)


def _match(db: Session, obs: Observation) -> Opportunity | None:
    if obs.external_id:
        row = db.scalar(select(Opportunity).where(Opportunity.external_id == obs.external_id))
        if row is not None:
            return row
    if obs.identity:
        region, customer, project, part = obs.identity
        stmt = select(Opportunity).where(
            Opportunity.region == region, Opportunity.customer == customer,
            Opportunity.project == project, Opportunity.part_number == part,
        )
        return db.scalar(stmt)
    return None


def _current_trust(db: Session, opp: Opportunity, field_name: str) -> int:
    param = PARAMS.by_name(FIELD_TO_PARAM_NAME[field_name]).id
    latest = db.scalars(
        select(FieldValueRow).where(FieldValueRow.opportunity_id == opp.id, FieldValueRow.param == param)
        .order_by(FieldValueRow.captured_at.desc())
    ).first()
    return latest.trust if latest is not None else TRUST_LEVELS["import"]


def _same(a, b) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    try:
        return abs(float(a) - float(b)) < 1e-9
    except (TypeError, ValueError):
        return str(a).strip().lower() == str(b).strip().lower()


def apply_observations(db: Session, spec: ConnectorSpec, observations: list[Observation], *,
                       actor: str, ref: str, dry_run: bool = False) -> PullResult:
    result = PullResult(connector=spec.name, ref=ref, observations=len(observations), matched=0, unmatched=0,
                        applied=0, reconciliation_items=0, unchanged=0, dry_run=dry_run)
    for obs in observations:
        opp = _match(db, obs)
        if opp is None:
            result.unmatched += 1
            result.details.append({"field": obs.field, "value": obs.value, "external_id": obs.external_id,
                                   "identity": obs.identity, "outcome": "unmatched"})
            continue
        result.matched += 1
        if obs.field not in FIELD_TO_PARAM_NAME:
            result.details.append({"opportunity": opp.external_id, "field": obs.field, "outcome": "unknown field"})
            continue
        param = PARAMS.by_name(FIELD_TO_PARAM_NAME[obs.field]).id
        current = getattr(opp, obs.field, None)
        # The trust of what is on the row now, read before this observation is
        # recorded so the observation never out-ranks itself.
        current_trust = _current_trust(db, opp, obs.field)
        if not dry_run:
            db.add(FieldValueRow(opportunity_id=opp.id, param=param, value=str(obs.value), source=spec.source,
                                 trust=spec.trust, captured_at=obs.observed_at))
        if _same(current, obs.value):
            result.unchanged += 1
            continue
        # An empty field has no trust to defend: any connector may fill it.
        fills_blank = current is None and obs.field in APPLICABLE_FIELDS
        if fills_blank or (obs.field in APPLICABLE_FIELDS and spec.trust > current_trust):
            if not dry_run:
                setattr(opp, obs.field, obs.value)
            result.applied += 1
            result.details.append({"opportunity": opp.external_id, "field": obs.field, "from": current,
                                   "to": obs.value, "outcome": "applied", "trust": f"{spec.trust} > {current_trust}"})
            continue
        # Equal/lower trust, or a gated field: a question for a person.
        if not dry_run:
            pending = db.scalars(select(Proposal).where(
                Proposal.opportunity_id == opp.id, Proposal.kind == "reconciliation", Proposal.status == "pending",
            )).all()
            duplicate = any((p.transition or {}).get("field") == obs.field
                            and _same((p.transition or {}).get("observed_value"), _jsonable(obs.value)) for p in pending)
            if not duplicate:
                db.add(Proposal(
                    opportunity_id=opp.id, rubric_version_id=_version_id(db), kind="reconciliation",
                    transition={
                        "field": obs.field, "current_value": _jsonable(current), "observed_value": _jsonable(obs.value),
                        "source": spec.source, "trust": spec.trust, "current_trust": current_trust,
                        "ref": obs.ref, "gated": obs.field in GATED_FIELDS,
                        "reason": ("a lifecycle field is never written by a connector" if obs.field in GATED_FIELDS
                                   else f"{spec.source} (trust {spec.trust}) does not out-rank the value on the row (trust {current_trust})"),
                    },
                    base_confidence=opp.confidence, proposed_confidence=opp.confidence, factors=[], flags={},
                    status="pending", band_crossing=False,
                ))
        result.reconciliation_items += 1
        result.details.append({"opportunity": opp.external_id, "field": obs.field, "current": _jsonable(current),
                               "observed": _jsonable(obs.value), "outcome": "reconciliation"})
    db.flush()
    return result


def _jsonable(v):
    return v.isoformat() if hasattr(v, "isoformat") else v


def _version_id(db: Session) -> str:
    from app.services.rubric_versions import current_version, publish_v1

    v = current_version(db)
    if v is None:
        v = publish_v1(db, published_by="connector-bootstrap")
    return v.id
