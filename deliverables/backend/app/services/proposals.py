"""
Proposals: raising one, and a person resolving it (WBS 7.0, 8.1, 10.5).

The evidence bundle carries no computed revenue. Plate 2 of
docs/02-architecture/OppTrack_Layer_Diagrams.html is explicit about where the
lanes cross: the model receives context and returns percentage points, and
Sales/Adjusted Revenue are computed in code it cannot reach. evidence_bundle()
below is a whitelist for that reason -- adding a field is a deliberate act, and
C1/C2 are not in it.

Resolving a proposal is the only path that changes Opportunity.confidence, and
it always writes a confidence_event first. Three rules are enforced here in code
rather than in the interface, matching enforcement points 4-6 of the product
document's Users & access section:

- a reviewer cannot approve or override a row they own (separation of duties);
- an override must cite a code from the override_reason vocabulary
  (app/registry/reason_codes.py), not free prose;
- the actor and their role are written with the event, before the call returns.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models.confidence_event import ConfidenceEvent
from app.db.models.opportunity import Opportunity
from app.db.models.proposal import Proposal
from app.db.models.rubric_version import RubricVersion
from app.judgment.contract import ConfidenceProposal, ContractViolation, Factor
from app.judgment.reply_guards import ReplyCheck, check_factors
from app.judgment.rubric import PROMPT_VERSION, citable_text
from app.registry.reason_codes import LOSS_REASON_CODES, OVERRIDE_REASON_CODES, REJECTION_REASON_CODES
from app.services.financials import financials_for
from app.services.portfolio import PortfolioShares
from app.services.rubric_versions import (
    baseline_for,
    caps_of,
    enabled_factor_keys,
    factor_caps_of,
    is_forbidden,
    review_policy_of,
)

# Fields the judgment layer is allowed to see. Deliberately excludes
# eau_kpcs * disty_asp and everything derived from them.
EVIDENCE_FIELDS = (
    "region", "customer", "end_customer", "project", "application", "product_line",
    "part_number", "design_status", "stage", "mp_date", "competitor_part", "owner",
    "evidence", "confidence_rationale", "confidence",
)

# Decision register #58: the fields an opportunity must carry. J-12 (data
# completeness) fires on any of these being null, blank, "TBD" or the backfill
# placeholder "Unassigned" -- a placeholder is an absence that got a name.
REQUIRED_FOR_COMPLETENESS = (
    "region", "customer", "end_customer", "project", "application", "product_line",
    "part_number", "design_status", "stage", "eau_kpcs", "disty_asp", "confidence",
    "owner", "confidence_rationale",
)
_PLACEHOLDERS = frozenset({"", "tbd", "n/a", "unassigned", "none"})


def missing_required(opp: Opportunity) -> list[str]:
    missing = []
    for name in REQUIRED_FOR_COMPLETENESS:
        value = getattr(opp, name, None)
        if value is None or (isinstance(value, str) and value.strip().lower() in _PLACEHOLDERS):
            missing.append(name)
    return missing


class ProposalError(ValueError):
    """A refused review action -- surfaced as a 400/403 by the router, never as
    a silently skipped write."""


def evidence_bundle(
    opp: Opportunity,
    *,
    version: RubricVersion | None = None,
    calibration=None,
    matrix_a_baseline: float | None = None,
    portfolio: PortfolioShares | None = None,
    overdue_milestones: list | None = None,
    days_in_stage: float | None = None,
    stage_median_days: float | None = None,
    sop_slip_months: float | None = None,
    precedents: list | None = None,
) -> dict:
    """What the model is shown for one row. Row fields plus derived context;
    never a revenue figure. Underscore keys are the derived context each Matrix
    B rule declares in `requires`; a None there leaves that rule dark."""
    bundle = {field: getattr(opp, field) for field in EVIDENCE_FIELDS}
    bundle["mp_date"] = bundle["mp_date"].isoformat() if bundle["mp_date"] else None

    # Matrix A, as config the model reads rather than infers (WBS 7.3).
    if version is not None:
        bundle["matrix_a_baseline"] = baseline_for(version, opp.design_status, opp.stage)
        bundle["matrix_a_forbidden"] = is_forbidden(version, opp.design_status, opp.stage)
    else:
        bundle["matrix_a_baseline"] = matrix_a_baseline
        bundle["matrix_a_forbidden"] = None

    # Derived, non-currency context. C3 and C6 are ratios; neither is a dollar.
    fin = financials_for(opp)
    bundle["_set_volume_ksets"] = fin.set_volume
    bundle["_channel_margin_pct"] = fin.channel_margin_pct
    bundle["_missing_required"] = missing_required(opp)
    bundle["_portfolio"] = portfolio.as_bundle() if portfolio is not None else None
    bundle["_overdue_milestones"] = overdue_milestones
    bundle["_days_in_stage"] = days_in_stage
    bundle["_stage_median_days"] = stage_median_days
    bundle["_sop_slip_months"] = sop_slip_months
    # L3 precedent (WBS 7.5): scrubbed notes from comparable sockets, quotes
    # only, never a figure. None when the assembler found nothing.
    bundle["_precedents"] = precedents or None
    # Present, and usually None: the factor guard reads it to decide whether
    # submitter_calibration is assessable at all (app/judgment/reply_guards.py).
    bundle["_calibration"] = calibration
    return bundle


def lifecycle_bands(version: RubricVersion) -> list[dict]:
    """Bands come from the published version or do not exist. The v1 template
    derives them from the Matrix A baselines (app/services/rubric_versions.py);
    a version published without them leaves band crossing undecidable, and an
    undecidable proposal queues."""
    return (version.rubric_factors or {}).get("lifecycle_bands") or []


def band_of(bands: list[dict], confidence: float) -> str | None:
    """Bands are half-open [min, max): a confidence exactly on a boundary
    belongs to the upper band, so 0.65 is Design In, not early."""
    for band in bands:
        low = band.get("min")
        high = band.get("max")
        if low is not None and confidence < low:
            continue
        if high is not None and confidence >= high:
            continue
        return band.get("label")
    return None


def crosses_band(version: RubricVersion, base: float, proposed: float) -> bool | None:
    """True/False when the published version defines bands; None when it does
    not -- and a None is queued for a person, never auto-applied."""
    bands = lifecycle_bands(version)
    if not bands:
        return None
    return band_of(bands, base) != band_of(bands, proposed)


@dataclass
class RaisedProposal:
    proposal: Proposal
    check: ReplyCheck
    event: ConfidenceEvent


def raise_proposal(
    db: Session,
    opp: Opportunity,
    version: RubricVersion,
    raw_factors: list,
    *,
    mode: str,
    model_id: str | None,
    run_id: str | None = None,
    actor: str = "agent",
    bundle: dict | None = None,
) -> RaisedProposal:
    """Runs the reply guards, builds the ConfidenceProposal contract, writes the
    proposal and its confidence_event. Does not change Opportunity.confidence --
    only a resolution does that, and only after the review policy says it may.
    `bundle` is the evidence bundle the scorer was given; pass it so the
    citation guard checks quotes against the same text the model saw."""
    caps = caps_of(version)
    if bundle is None:
        bundle = evidence_bundle(opp, version=version)
    check = check_factors(
        raw_factors,
        bundle,
        allowed_keys=enabled_factor_keys(version),
        factor_cap_pp=caps.factor_cap_pp,
        factor_caps=factor_caps_of(version),
        citable=citable_text(bundle),
    )

    flags: dict = {}
    ceiling = caps.confidence_ceiling if caps.confidence_ceiling is not None else 0.95
    floor = caps.confidence_floor if caps.confidence_floor is not None else 0.05
    run_cap = caps.run_cap_pp if caps.run_cap_pp is not None else 20.0

    # Per-run cap (decision #19): total movement in one run is clipped to the
    # cap and the proposal is flagged so it queues for a person regardless of
    # the review policy.
    total_pp = check.total_adjustment_pp
    if abs(total_pp) > run_cap:
        flags["run_cap_clipped_from_pp"] = total_pp
        total_pp = run_cap if total_pp > 0 else -run_cap

    proposed = opp.confidence + total_pp / 100.0
    if proposed > ceiling or proposed < floor:
        flags["clamped_from"] = proposed
    proposed = max(floor, min(ceiling, proposed))

    # The contract is the last word: an out-of-bounds proposal cannot exist as
    # an object. The guards above are what make this pass; if it does not,
    # the failure is recorded on the row rather than a number reaching a
    # reviewer with the checks quietly relaxed.
    try:
        contract = ConfidenceProposal(
            opportunity_id=opp.id,
            prior=opp.confidence,
            proposed=proposed,
            factors=tuple(
                Factor(rule_id=f.rule_id or "", key=f.key, delta_pp=f.confidence_adjustment_pct,
                       quote=f.quote, rationale=f.rationale, model_confidence=f.confidence)
                for f in check.fired
            ),
            rubric_version=version.label,
            floor=floor, ceiling=ceiling, run_cap_pp=run_cap,
            factor_caps_pp=factor_caps_of(version),
        )
    except ContractViolation as exc:
        # Only reachable if a fired factor slipped past a guard with a bad
        # sign, cap or citation, or the clamp produced an impossible pair.
        # Recorded as a no-change proposal with the violation on it.
        flags["contract_violation"] = str(exc)
        proposed = opp.confidence
        contract = None

    band_crossing = crosses_band(version, opp.confidence, proposed)

    proposal = Proposal(
        opportunity_id=opp.id,
        rubric_version_id=version.id,
        run_id=run_id,
        kind="confidence",
        base_confidence=opp.confidence,
        proposed_confidence=proposed,
        factors=[
            {
                "rule_id": f.rule_id, "key": f.key, "applies": f.applies,
                "confidence_adjustment_pct": f.confidence_adjustment_pct,
                "quote": f.quote, "rationale": f.rationale, "confidence": f.confidence,
                "accepted": f.accepted, "guard": f.guard, "detail": f.detail,
                "clipped_from": f.clipped_from,
            }
            for f in check.factors
        ],
        flags=flags,
        status="pending",
        band_crossing=band_crossing,
    )
    db.add(proposal)
    db.flush()

    event = ConfidenceEvent(
        opportunity_id=opp.id,
        proposal_id=proposal.id,
        rubric_version_id=version.id,
        event_type="proposal",
        base_confidence=opp.confidence,
        resulting_confidence=proposed,
        model_id=model_id,
        prompt_version=f"{PROMPT_VERSION};rubric:{version.label}",
        actor=actor,
        actor_role="service",
        note=f"{mode} scorer; {len(check.fired)} factors fired, "
             f"{len(check.not_assessable)} not assessable, {len(check.rejected)} rejected"
             + (f"; flags {sorted(flags)}" if flags else ""),
    )
    db.add(event)
    db.flush()
    _emit(db, "proposal.raised", {"proposal_id": proposal.id, "opportunity_id": opp.id, "external_id": opp.external_id,
                                  "project": opp.project, "base": opp.confidence, "proposed": proposed,
                                  "fired": [f.rule_id for f in check.fired], "flags": flags})
    return RaisedProposal(proposal=proposal, check=check, event=event)


def _emit(db: Session, event: str, payload: dict) -> None:
    """Outbound webhook (WBS 10.13). Never lets a delivery failure fail the
    write that caused it: the delivery row records the failure instead."""
    try:
        from app.services.webhooks import deliver_event

        deliver_event(db, event=event, payload=payload)
    except Exception as exc:  # noqa: BLE001
        print(f"[webhooks] {event}: {type(exc).__name__}: {exc}")


def _resolve_reconciliation(
    db: Session, proposal: Proposal, opp: Opportunity, *, action: str, actor: str, actor_role: str,
    reason_code: str | None, note: str | None,
) -> ConfidenceEvent | None:
    """A connector's value that did not out-rank the row (WBS 11.2). Approve
    applies it as a human-reconciled value at the top of the ladder -- through
    record_transition for a lifecycle field, which needs the close grant and a
    loss reason where the target is Lost; reject keeps the row and records why."""
    from app.db.models.field_value import TRUST_LEVELS
    from app.db.models.field_value import FieldValue as FieldValueRow
    from app.intake.provenance import FIELD_TO_PARAM_NAME
    from app.registry.parameters import PARAMS
    from app.services.state_transitions import record_transition

    spec = proposal.transition or {}
    field_name, observed = spec.get("field"), spec.get("observed_value")
    if action == "reject":
        if reason_code is None or not REJECTION_REASON_CODES.validate(reason_code):
            raise ProposalError(f"a rejection must cite a code from the rejection_reason vocabulary "
                                f"{sorted(REJECTION_REASON_CODES.codes)}")
        _resolved(proposal, "rejected", actor)
        db.flush()
        return None
    if action != "approve":
        raise ProposalError("a reconciliation item is approved (take the connector's value) or rejected (keep the row's)")
    if field_name in ("design_status", "stage"):
        if field_name == "design_status" and str(observed).lower() == "lost" and (
            reason_code is None or not LOSS_REASON_CODES.validate(reason_code)
        ):
            raise ProposalError("taking a Lost status from a connector still needs a loss_reason code from the reviewer")
        record_transition(db, opp, field=field_name, to_value=str(observed), actor=actor,
                          reason_code=reason_code if field_name == "design_status" else None)
    elif field_name == "confidence":
        raise ProposalError("confidence is never taken from a connector; override the proposal with your own value instead")
    else:
        value = observed
        if field_name == "mp_date" and isinstance(observed, str):
            from datetime import date as _date
            value = _date.fromisoformat(observed)
        setattr(opp, field_name, value)
    db.add(FieldValueRow(opportunity_id=opp.id, param=PARAMS.by_name(FIELD_TO_PARAM_NAME[field_name]).id,
                         value=str(observed), source="human_reconciled", trust=TRUST_LEVELS["human_reconciled"]))
    _resolved(proposal, "approved", actor)
    db.flush()
    return None


def _resolve_transition(
    db: Session, proposal: Proposal, opp: Opportunity, *, action: str, actor: str, actor_role: str,
    reason_code: str | None, note: str | None,
) -> ConfidenceEvent | None:
    """A transition proposal (WBS 8.3): approving it is the sanctioned lifecycle
    write -- record_transition, the same path a manual move takes, so
    state_history carries the actor who signed off. A Lost transition needs
    the loss reason code from the reviewer (WBS 8.4); the agent never
    supplies one. Override does not apply: there is no value to override."""
    from app.services.state_transitions import record_transition

    if actor and opp.owner and actor.strip().lower() == opp.owner.strip().lower():
        raise ProposalError(
            "a reviewer cannot approve or reject a lifecycle proposal on a row they own "
            f"(actor and owner are both {opp.owner!r})"
        )
    spec = proposal.transition or {}
    to_value = spec.get("to_value")
    if action == "reject":
        if reason_code is None or not REJECTION_REASON_CODES.validate(reason_code):
            raise ProposalError(
                f"a rejection must cite a code from the rejection_reason vocabulary "
                f"{sorted(REJECTION_REASON_CODES.codes)}"
            )
        _resolved(proposal, "rejected", actor)
        db.flush()
        return None
    if action == "override":
        raise ProposalError("a lifecycle proposal is approved or rejected; there is no value to override")
    if action != "approve":
        raise ProposalError(f"unknown action {action!r}; expected approve or reject")
    if to_value == "Lost" and (reason_code is None or not LOSS_REASON_CODES.validate(reason_code)):
        raise ProposalError(
            f"approving a Design Lost transition needs a loss_reason code from "
            f"{sorted(LOSS_REASON_CODES.codes)} -- the agent proposes the move, the reviewer records why"
        )
    record_transition(
        db, opp, field=spec.get("field", "design_status"), to_value=to_value, actor=actor,
        reason_code=reason_code if to_value == "Lost" else None,
    )
    _resolved(proposal, "approved", actor)
    db.flush()
    return None


def _feedback_details(proposal: Proposal, rejected_factors: list[str] | None) -> dict:
    """Normalises the reviewer's disagreement to rule ids. Given nothing, a
    rejection is attributed to every factor that fired -- the reviewer refused
    the proposal as a whole, and each fired rule takes the signal."""
    fired = [f for f in (proposal.factors or []) if f.get("applies") and f.get("accepted")]
    by_key = {f.get("key"): f.get("rule_id") for f in fired}
    by_id = {f.get("rule_id"): f.get("rule_id") for f in fired}
    if rejected_factors:
        ids = [by_id.get(x) or by_key.get(x) for x in rejected_factors]
        ids = [i for i in ids if i]
    else:
        ids = [f.get("rule_id") for f in fired if f.get("rule_id")]
    return {"rejected_factors": sorted(set(ids))}


def _resolved(proposal: Proposal, status: str, actor: str) -> None:
    proposal.status = status
    proposal.resolved_at = datetime.now(timezone.utc)
    proposal.resolved_by = actor


def resolve_proposal(
    db: Session,
    proposal: Proposal,
    opp: Opportunity,
    *,
    action: str,
    actor: str,
    actor_role: str,
    value: float | None = None,
    reason_code: str | None = None,
    note: str | None = None,
    rejected_factors: list[str] | None = None,
) -> ConfidenceEvent:
    """action: approve | reject | override. Returns the audit event; the caller
    commits. A rejection cites a rejection_reason code and, optionally, the
    factors it disagrees with (WBS 8.7) -- rejections are the calibration
    signal, and a log that cannot say *what* was rejected cannot aggregate it."""
    if proposal.status != "pending":
        raise ProposalError(f"proposal is already {proposal.status}")
    if proposal.kind == "reconciliation":
        return _resolve_reconciliation(
            db, proposal, opp, action=action, actor=actor, actor_role=actor_role,
            reason_code=reason_code, note=note,
        )
    if proposal.kind == "transition":
        return _resolve_transition(
            db, proposal, opp, action=action, actor=actor, actor_role=actor_role,
            reason_code=reason_code, note=note,
        )

    # Enforcement point 5: checked in code, not in the interface. An owner who
    # calls this API directly gets the same refusal a hidden button would imply.
    if actor and opp.owner and actor.strip().lower() == opp.owner.strip().lower():
        raise ProposalError(
            "a reviewer cannot approve, reject or override a proposal on a row they own "
            f"(actor and owner are both {opp.owner!r})"
        )

    if action == "approve":
        if (proposal.flags or {}).get("contract_violation"):
            raise ProposalError(
                "this proposal failed the ConfidenceProposal contract and proposes no change; "
                "reject it or override with your own value"
            )
        resulting = proposal.proposed_confidence
        event_type = "approval"
    elif action == "reject":
        if reason_code is None or not REJECTION_REASON_CODES.validate(reason_code):
            raise ProposalError(
                f"a rejection must cite a code from the rejection_reason vocabulary "
                f"{sorted(REJECTION_REASON_CODES.codes)}"
            )
        resulting = opp.confidence
        event_type = "rejection"
    elif action == "override":
        if value is None:
            raise ProposalError("an override needs a confidence value")
        if not 0.0 <= value <= 1.0:
            raise ProposalError("confidence must be between 0 and 1")
        if reason_code is None or not OVERRIDE_REASON_CODES.validate(reason_code):
            raise ProposalError(
                f"an override must cite a code from the override_reason vocabulary "
                f"{sorted(OVERRIDE_REASON_CODES.codes)}"
            )
        resulting = value
        event_type = "override"
    else:
        raise ProposalError(f"unknown action {action!r}; expected approve, reject or override")

    event = ConfidenceEvent(
        opportunity_id=opp.id,
        proposal_id=proposal.id,
        rubric_version_id=proposal.rubric_version_id,
        event_type=event_type,
        base_confidence=opp.confidence,
        resulting_confidence=resulting,
        model_id=None,  # a human decision, not a model call
        prompt_version=None,
        actor=actor,
        actor_role=actor_role,
        reason_code=reason_code,
        note=note,
        details=_feedback_details(proposal, rejected_factors) if action in ("reject", "override") else None,
    )
    db.add(event)

    if action != "reject":
        opp.confidence = resulting
    _resolved(proposal, {"approve": "approved", "reject": "rejected", "override": "overridden"}[action], actor)
    db.flush()
    _emit(db, "proposal.resolved", {"proposal_id": proposal.id, "opportunity_id": opp.id, "external_id": opp.external_id,
                                    "action": action, "resulting_confidence": resulting, "actor": actor,
                                    "reason_code": reason_code})
    return event


def must_queue(proposal: Proposal, version: RubricVersion) -> tuple[bool, str]:
    """Whether a proposal has to reach a person, and why. Review policy is a
    published setting (decision #21 vs Plate 2 step 9): "gate_all" queues every
    proposal; "gate_band_crossing" auto-applies one that crosses no band and
    carries no flag. Undecidable band crossing always queues."""
    if review_policy_of(version) != "gate_band_crossing":
        return True, "review policy is gate_all: every proposal reaches a person"
    if proposal.flags:
        return True, f"flagged: {', '.join(sorted(proposal.flags))}"
    if proposal.band_crossing is None:
        return True, "no lifecycle bands published, so band crossing is undecidable"
    if proposal.band_crossing:
        return True, "crosses a lifecycle band"
    return False, "no band crossed and nothing flagged"


def auto_apply(db: Session, proposal: Proposal, opp: Opportunity, version: RubricVersion) -> ConfidenceEvent:
    """Plate 2, step 9: a proposal that crosses no lifecycle band applies on its
    own -- "which is the difference between a review queue and a rubber stamp".
    Only ever reached when band_crossing is explicitly False; a None (no ratified
    bands) queues instead."""
    event = ConfidenceEvent(
        opportunity_id=opp.id,
        proposal_id=proposal.id,
        rubric_version_id=version.id,
        event_type="auto_applied",
        base_confidence=opp.confidence,
        resulting_confidence=proposal.proposed_confidence,
        model_id=None,
        prompt_version=f"rubric:{version.label}",
        actor="agent",
        actor_role="service",
        note="no lifecycle band crossed; applied without a reviewer",
    )
    db.add(event)
    opp.confidence = proposal.proposed_confidence
    _resolved(proposal, "applied", "agent")
    db.flush()
    return event
