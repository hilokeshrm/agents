"""
One run, ten steps (docs/02-architecture/OppTrack_Layer_Diagrams.html, Plate 2)
-- the executable version of that plate, and the source of everything the Runs &
audit screen (WBS 10.9) shows.

Three properties of the plate are kept here rather than approximated:

1. The two dashed steps -- 04 Precedent and 08 Lifecycle -- are architecturally
   present and deliberately not running. They report `skipped` with the reason,
   never a fabricated result. Step 4 needs resolved outcomes and a retrieval
   store (app/memory/ is an empty package); step 8 needs ratified lifecycle
   bands (WBS 1.1 Q1). A run that pretended either had happened would be lying
   in exactly the way this architecture exists to prevent.
2. The lanes cross where the plate says they cross: step 5 sends an evidence
   bundle carrying no C1/C2 (app/services/proposals.py), step 6 checks the reply
   (app/judgment/reply_guards.py), and only then does step 7 re-run step 3's
   function -- the same function, not a second implementation of it.
3. A failed run is recorded and completes as a failure. The scorer falling back
   from live to mock is reported in `mode`, not hidden; a raised exception is
   written to the run row before it propagates.

A run scores live opportunity rows, so `snapshot_id` is null: there is no sealed
workbook behind it. That is a real difference from the plate's step 1, stated in
the step trace rather than papered over with a synthetic snapshot.
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calc.engine import compute_project_financials
from app.services.financials import engine_row
from app.calc.severity import BLOCKING, classify_severity
from app.db.models.calibration import Calibration
from app.db.models.opportunity import Opportunity
from app.db.models.proposal import Proposal
from app.db.models.run import Run
from app.db.models.rubric_version import RubricVersion
from app.intake.canonicalize import canonicalize_row
from app.judgment.rubric import score_confidence_factors
from app.services.portfolio import PortfolioShares, portfolio_context
from app.services.proposals import auto_apply, evidence_bundle, must_queue, raise_proposal
from app.services.rubric_versions import is_forbidden, review_policy_of
from app.services.transitions import detect_candidates, open_transition_ids, propose_transition

DETERMINISTIC, JUDGMENT, HUMAN = "deterministic", "judgment", "human"


def _step(n: int, name: str, lane: str, status: str, detail: str) -> dict:
    return {"n": n, "name": name, "lane": lane, "status": status, "detail": detail}


def _row_dict(opp: Opportunity) -> dict:
    """The engine's row plus the two fields the validate step needs (severity and
    canonicalisation read `owner` and `competitor_part`, which the calc engine
    does not)."""
    return {
        **engine_row(opp),
        "competitor_part": opp.competitor_part,
        "owner": opp.owner,
    }


def execute_run(db: Session, *, version: RubricVersion, actor: str, opportunity_ids: list[str] | None = None) -> Run:
    run = Run(
        kind="judgment", status="running", mode="mock",
        rubric_version_id=version.id, snapshot_id=None, actor=actor,
        steps=[], counts={},
    )
    db.add(run)
    db.flush()

    steps: list[dict] = []
    counts: dict = {}

    try:
        # --- 01 Intake -------------------------------------------------------
        stmt = select(Opportunity)
        if opportunity_ids:
            stmt = stmt.where(Opportunity.id.in_(opportunity_ids))
        rows = list(db.scalars(stmt.order_by(Opportunity.created_at)).all())
        counts["rows_read"] = len(rows)
        steps.append(_step(
            1, "Intake", DETERMINISTIC, "ran",
            f"{len(rows)} opportunity rows read from the database. No workbook snapshot: this run "
            f"scores live rows, so there is no sealed source to hash (WBS 3.2 covers the import path).",
        ))

        # --- 02 Validate -----------------------------------------------------
        blocked: list[Opportunity] = []
        blocking_msgs: list[str] = []
        contradictions: list[str] = []
        for opp in rows:
            row = _row_dict(opp)
            if classify_severity(row) == BLOCKING:
                blocked.append(opp)
                blocking_msgs.append(f"{opp.project}: a field revenue cannot be computed without is missing")
                continue
            # Decision #10: a forbidden (Design Status, Stage) cell is a blocking
            # finding -- the row is excluded from totals and not scored, rather
            # than scored with a haircut for a contradiction a person has to fix.
            if is_forbidden(version, opp.design_status, opp.stage):
                blocked.append(opp)
                blocking_msgs.append(
                    f"{opp.project}: {opp.design_status} at {opp.stage} is forbidden in "
                    f"Matrix A version {version.label} (V-b)"
                )
                continue
            findings = canonicalize_row(row).findings
            if findings:
                contradictions.extend(f"{opp.project}: {f.message}" for f in findings)
        scorable = [o for o in rows if o not in blocked]
        counts["blocked"] = len(blocked)
        counts["advisory"] = len(contradictions)
        steps.append(_step(
            2, "Validate", DETERMINISTIC, "ran",
            f"{len(blocked)} rows blocking (excluded from every total, WBS 4.2; a forbidden Matrix A "
            f"pairing is blocking per decision #10), {len(contradictions)} advisory findings."
            + ("" if not blocking_msgs else " Blocking: " + "; ".join(blocking_msgs[:4]))
            + ("" if not contradictions else " Advisory: " + "; ".join(contradictions[:4])),
        ))

        # --- 03 Compute ------------------------------------------------------
        base_financials = [compute_project_financials(_row_dict(o)) for o in scorable]
        base_total = sum(f.adjusted_revenue_k for f in base_financials)
        counts["base_adjusted_revenue_k"] = base_total
        steps.append(_step(
            3, "Compute", DETERMINISTIC, "ran",
            f"C1/C2 over {len(scorable)} rows: ${base_total:,.1f}K adjusted revenue, "
            f"app/calc/engine.py, no model involvement.",
        ))

        # --- 04 Precedent ----------------------------------------------------
        from app.memory import assemble, bundle_precedents, refresh_from_rows

        calibrations = {c.owner: c for c in db.scalars(select(Calibration)).all() if c.owner}
        refresh_from_rows(db, scorable, vintage=run.id)
        precedent_packs = {o.id: assemble(db, opportunity=o) for o in scorable}
        with_precedent = sum(1 for p in precedent_packs.values() if p.precedents)
        steps.append(_step(
            4, "Precedent", JUDGMENT, "ran" if with_precedent else "skipped",
            f"L3 memory (app/memory): filtered by region, product line and recency before ranking; "
            f"{with_precedent} of {len(scorable)} rows have comparable precedent, top-{6} within a token budget. "
            f"Numbers and pricing are scrubbed at write time. Calibration priors: {len(calibrations)} owners."
            + ("" if with_precedent else " Nothing comparable yet: factors needing precedent stay dark."),
        ))

        # --- 05 Score --------------------------------------------------------
        # A row already carrying an open proposal is left alone: re-proposing
        # over a pending decision would put two live proposals on one row and
        # silently make the reviewer's queue ambiguous.
        pending_ids = set(db.scalars(
            select(Proposal.opportunity_id).where(Proposal.status == "pending")
        ).all())
        already_queued = [o for o in scorable if o.id in pending_ids]
        to_score = [o for o in scorable if o.id not in pending_ids]
        counts["skipped_open_proposal"] = len(already_queued)

        # Portfolio context over the scorable set (WBS 7.1): the shares J-05
        # needs. Computed once, sliced per row; the model sees ratios, not the
        # revenue behind them.
        shares = portfolio_context(base_financials)

        scored: list[tuple[Opportunity, list, dict]] = []
        modes = set()
        fallback_errors: list[str] = []
        for opp in to_score:
            bundle = evidence_bundle(
                opp,
                version=version,
                calibration=_calibration_summary(calibrations.get(opp.owner)),
                portfolio=shares.get(opp.project),
                precedents=bundle_precedents(precedent_packs[opp.id]),
            )
            result = score_confidence_factors(bundle)
            modes.add(result["mode"])
            if result.get("fallback_error"):
                fallback_errors.append(f"{opp.project}: {result['fallback_error']}")
            scored.append((opp, result["factors"], bundle))
        run.mode = "live" if modes == {"live"} else ("mixed" if len(modes) > 1 else "mock")
        counts["scored"] = len(scored)
        counts["live_fallbacks"] = len(fallback_errors)
        steps.append(_step(
            5, "Score", JUDGMENT, "ran",
            f"one call per row, {len(scored)} rows"
            + (f" ({len(already_queued)} skipped, already carrying an open proposal)" if already_queued else "")
            + f", {run.mode} scorer. The bundle carries the row, its Matrix A cell, its portfolio shares "
            f"and derived ratios -- no C1, no C2 -- and the reply is percentage points, quotes and "
            f"rationales, never a figure."
            + (f" {len(fallback_errors)} LIVE call(s) failed and fell back to MOCK: "
               + "; ".join(fallback_errors[:3]) if fallback_errors else ""),
        ))

        # --- 06 Check + 09 Approve (queue) ----------------------------------
        fired = rejected = not_assessable = clipped = 0
        queued = auto_applied = 0
        proposals: list[Proposal] = []
        for opp, raw_factors, bundle in scored:
            raised = raise_proposal(
                db, opp, version, raw_factors,
                mode=run.mode,
                model_id=None if run.mode == "mock" else _model_id(),
                run_id=run.id,
                actor="agent",
                bundle=bundle,
            )
            fired += len(raised.check.fired)
            rejected += len(raised.check.rejected)
            not_assessable += len(raised.check.not_assessable)
            clipped += len(raised.check.clipped)
            proposals.append(raised.proposal)

        steps.append(_step(
            6, "Check", JUDGMENT, "ran",
            f"{fired} factors fired, {not_assessable} not assessable, {rejected} rejected by a guard, "
            f"{clipped} clipped to a cap. Ten guards, app/judgment/reply_guards.py, then the "
            f"ConfidenceProposal contract -- rejected factors are kept on the proposal, not dropped.",
        ))

        # --- 07 Recompute ----------------------------------------------------
        proposed_by_opp = {p.opportunity_id: p.proposed_confidence for p in proposals}
        # Over the same row set step 3 measured, so the delta is a like-for-like
        # comparison: a row skipped at step 5 contributes its entered confidence
        # to both totals rather than dropping out of one of them.
        proposed_total = 0.0
        for opp in scorable:
            row = _row_dict(opp)
            row["confidence"] = proposed_by_opp.get(opp.id, opp.confidence)
            proposed_total += compute_project_financials(row).adjusted_revenue_k
        counts["proposed_adjusted_revenue_k"] = proposed_total
        counts["delta_adjusted_revenue_k"] = proposed_total - base_total
        steps.append(_step(
            7, "Recompute", DETERMINISTIC, "ran",
            f"the same function as step 3, called again with the proposed confidences: "
            f"${proposed_total:,.1f}K, a {proposed_total - base_total:+,.1f}K change. That the two "
            f"figures come from one function is what makes the delta mean anything.",
        ))

        # --- 08 Lifecycle ----------------------------------------------------
        # Decision #36: the agent never moves a record. A row whose own data
        # says it has resolved gets a transition proposal for a person with
        # the close grant. Detection runs over every scorable row, including
        # ones skipped at step 5 for carrying an open confidence proposal.
        already_open = open_transition_ids(db)
        candidates = [c for c in detect_candidates(scorable, as_of=datetime.now(timezone.utc).date())
                      if c.opportunity.id not in already_open]
        transition_proposals = [propose_transition(db, c, version, run_id=run.id) for c in candidates]
        counts["transition_proposals"] = len(transition_proposals)

        undecided = [p for p in proposals if p.band_crossing is None]
        band_note = (
            f"rubric version {version.label} publishes no lifecycle bands, so band crossing is undecidable "
            f"for {len(undecided)} proposals and each queues for a person"
            if undecided else
            f"{sum(1 for p in proposals if p.band_crossing)} of {len(proposals)} confidence proposals cross a "
            f"band in rubric version {version.label}; {sum(1 for p in proposals if p.flags)} carry a bounds flag"
        )
        moves = "; ".join(f"{c.opportunity.project} -> {c.to_value} ({c.reason})" for c in candidates[:4])
        steps.append(_step(
            8, "Lifecycle", HUMAN, "ran",
            f"{band_note}. {len(transition_proposals)} lifecycle transition(s) proposed for a person with the "
            f"close grant -- the agent moves nothing itself (decision #36)"
            + (f": {moves}" if moves else "") + ".",
        ))

        # --- 09 Approve ------------------------------------------------------
        policy = review_policy_of(version)
        for proposal in proposals:
            opp = next(o for o in to_score if o.id == proposal.opportunity_id)
            gate, _why = must_queue(proposal, version)
            if gate:
                queued += 1
            else:
                auto_apply(db, proposal, opp, version)
                auto_applied += 1
        counts["queued"] = queued
        counts["auto_applied"] = auto_applied
        steps.append(_step(
            9, "Approve", HUMAN, "ran",
            f"review policy {policy}: {queued} proposals queued for review, "
            f"{auto_applied} applied without a person.",
        ))

        # --- 10 Log ----------------------------------------------------------
        counts["proposals"] = len(proposals)
        steps.append(_step(
            10, "Log", DETERMINISTIC, "ran",
            f"{len(proposals)} confidence_event rows written, each stamping rubric version "
            f"{version.label} and the scorer mode. Append-only: nothing in this codebase updates "
            f"or deletes one.",
        ))

        run.status = "completed"
        _metric("runs", 1)
    except Exception as exc:  # noqa: BLE001 -- recorded, then re-raised by the caller
        run.status = "failed"
        _metric("run_failures", 1)
        run.error = f"{type(exc).__name__}: {exc}"
        steps.append(_step(len(steps) + 1, "Failed", DETERMINISTIC, "failed", run.error))
        run.steps = steps
        run.counts = counts
        run.finished_at = datetime.now(timezone.utc)
        db.flush()
        raise

    run.steps = steps
    run.counts = counts
    run.finished_at = datetime.now(timezone.utc)
    db.flush()
    try:
        from app.services.webhooks import deliver_event

        deliver_event(db, event="run.completed", payload={"run_id": run.id, "mode": run.mode, "counts": counts,
                                                          "rubric_version": version.label})
    except Exception as exc:  # noqa: BLE001
        print(f"[webhooks] run.completed: {type(exc).__name__}: {exc}")
    return run


def _calibration_summary(calibration: Calibration | None) -> dict | None:
    """The calibration record as plain JSON-serialisable data. The evidence
    bundle is serialised into the model prompt, so an ORM object here would fail
    the moment the scorer ran live -- and passing the row wholesale would also
    hand the model more than the factor needs."""
    if calibration is None:
        return None
    if not getattr(calibration, "reliable", False):
        # Decision #70: an unreliable prior is not handed to the model at all;
        # J-06 stays dark rather than scoring against two months of outcomes.
        return None
    return {
        "bias_pp": calibration.bias_pp,
        "sd_pp": getattr(calibration, "sd_pp", 0.0),
        "sample_size": calibration.sample_size,
        "window": f"{calibration.window_start.isoformat()}..{calibration.window_end.isoformat()}",
    }


def _metric(field: str, amount: int) -> None:
    try:
        from app.services.metrics import incr

        incr(field, amount)
    except Exception:  # noqa: BLE001 -- observability never breaks a run
        pass


def _model_id() -> str:
    from app.core.config import settings

    return settings.judgment_model


def single_row_bundle(db: Session, opp: Opportunity, version: RubricVersion) -> dict:
    """The bundle for one row scored outside a portfolio run (request-review).
    Portfolio shares are still computed, over every scorable row in the
    database, so J-05 can fire from the review console the same way it does in
    a run -- a single-row signature is exactly what left it dead before."""
    rows = list(db.scalars(select(Opportunity)).all())
    scorable = [
        o for o in rows
        if classify_severity(_row_dict(o)) != BLOCKING
        and not is_forbidden(version, o.design_status, o.stage)
    ]
    shares = portfolio_context([compute_project_financials(_row_dict(o)) for o in scorable])
    calibrations = {c.owner: c for c in db.scalars(select(Calibration)).all() if c.owner}
    return evidence_bundle(
        opp,
        version=version,
        calibration=_calibration_summary(calibrations.get(opp.owner)),
        portfolio=shares.get(opp.project),
    )
