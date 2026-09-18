"""
Direct-entry intake service (WBS 3.7) -- the one write path every source uses.

Direct entry, workbook import, CRM sync and API writes all end here (decision
#90). The service canonicalises, checks the Matrix A pairing (V-b), refuses a
row missing a calculation field, records advisory findings for a missing
required field, mints or preserves the Opportunity ID, writes provenance per
ParamSpec id, seeds the state and owner streams, and returns what it found.
A caller that wants different behaviour changes the policy here, not in one
of four routes.
"""

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.field_value import FieldValue as FieldValueRow
from app.db.models.finding import Finding
from app.db.models.opportunity import Opportunity, next_external_id
from app.db.models.owner_history import OwnerHistory
from app.intake.canonicalize import canonicalize_row
from app.intake.provenance import wrap_row
from app.intake.schema import CALC, REQUIRED, missing
from app.registry.reason_codes import LOSS_REASON_CODES
from app.services.rubric_versions import effective_version, is_forbidden
from app.services.state_transitions import seed_initial_state


class IntakeError(ValueError):
    """A refused row. `findings` carries the structured reasons."""

    def __init__(self, message: str, findings: list[dict] | None = None, status_code: int = 400,
                 structured: bool = False):
        super().__init__(message)
        self.findings = findings or []
        self.status_code = status_code
        # True when the API should return the findings list; otherwise the message.
        self.structured = structured

    @property
    def detail(self):
        return self.findings if self.structured else str(self)


@dataclass
class IntakeResult:
    opportunity: Opportunity
    advisories: list[dict] = field(default_factory=list)


def create_opportunity(
    db: Session,
    values: dict,
    *,
    source: str,
    trust: int,
    actor: str,
    snapshot_id: str | None = None,
) -> IntakeResult:
    """Creates one opportunity from already-typed values (a Pydantic model's
    dump, or an import row after coercion). Raises IntakeError rather than
    writing a row that cannot be computed."""
    result = canonicalize_row(values)
    if result.findings:
        raise IntakeError(
            "a required field did not canonicalise",
            [{"field": f.field, "raw_value": f.raw_value, "message": f.message} for f in result.findings],
            structured=True,
        )
    canonical = dict(result.canonical)

    calc_missing = missing(canonical, CALC)
    if calc_missing:
        raise IntakeError(
            f"row is missing a field revenue cannot be computed without: {', '.join(calc_missing)} (V-a)",
            [{"field": f, "raw_value": None, "message": "required for Sales Revenue"} for f in calc_missing],
        )

    version = effective_version(db)
    if is_forbidden(version, canonical["design_status"], canonical["stage"]):
        raise IntakeError(
            f"design status {canonical['design_status']!r} cannot be paired with stage "
            f"{canonical['stage']!r} under Matrix A version {version.label!r} (rule V-b)",
            [{"field": "stage", "raw_value": f"{canonical['design_status']} / {canonical['stage']}",
              "message": "forbidden pairing"}],
        )

    # A row entered as Lost is the same close the transition path gates: it needs
    # a loss reason from the vocabulary, and Matrix A carries it at 0.00, so a
    # non-zero confidence on it would be weighted revenue for a dead socket.
    loss_reason = canonical.pop("loss_reason", None) or values.get("loss_reason")
    if str(canonical["design_status"]).lower() == "lost":
        if not loss_reason:
            raise IntakeError(
                "a loss_reason code is required when an opportunity is entered as Lost",
                [{"field": "loss_reason", "raw_value": None, "message": "required for Lost"}],
            )
        if not LOSS_REASON_CODES.validate(loss_reason):
            raise IntakeError(
                f"{loss_reason!r} is not in the loss_reason vocabulary {sorted(LOSS_REASON_CODES.codes)}",
                [{"field": "loss_reason", "raw_value": loss_reason, "message": "not in vocabulary"}],
            )
        if float(canonical.get("confidence") or 0) != 0.0:
            raise IntakeError(
                "a Lost opportunity carries confidence 0.00 under Matrix A; enter 0 or a live status",
                [{"field": "confidence", "raw_value": canonical.get("confidence"), "message": "Lost is 0.00"}],
            )

    requested_external_id = canonical.pop("external_id", None)
    if requested_external_id:
        existing = db.scalar(select(Opportunity).where(Opportunity.external_id == requested_external_id))
        if existing is not None:
            raise IntakeError(f"external opportunity id {requested_external_id!r} already exists", status_code=409)

    opp = Opportunity(**canonical)
    opp.external_id = requested_external_id or next_external_id(db)
    db.add(opp)
    db.flush()

    # Provenance (WBS 3.6): every value that reached the row is also written as
    # a FieldValue, cited by ParamSpec id, before this returns -- including the
    # id the platform minted, so a crosswalk can cite where it came from.
    for fv in wrap_row({**canonical, "external_id": opp.external_id, "loss_reason": loss_reason},
                       source=source, trust=trust).values():
        db.add(FieldValueRow(
            opportunity_id=opp.id, param=fv.param, value=str(fv.value),
            source=fv.source, trust=fv.trust, captured_at=fv.at,
        ))

    seed_initial_state(db, opp, actor=actor, reason_code=loss_reason)
    db.add(OwnerHistory(opportunity_id=opp.id, from_owner=None, to_owner=opp.owner, actor=actor))

    # Decision #62: a missing required (non-calculation) field is advisory --
    # recorded on the row, never a reason to lose the opportunity.
    advisories = []
    for name in missing(canonical, REQUIRED):
        message = f"{name} is required by the intake schema and was not supplied (advisory, V-a)"
        db.add(Finding(opportunity_id=opp.id, snapshot_id=snapshot_id, rule_id="V-a",
                       severity="advisory", message=message))
        advisories.append({"field": name, "message": message})
    db.flush()
    return IntakeResult(opportunity=opp, advisories=advisories)
