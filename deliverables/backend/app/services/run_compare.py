"""
Run-to-run comparison (WBS 6.6, feeds 12.4).

Two runs over the same rows differ for exactly three reasons this system can
name: the rubric version, the prompt version, or the model (including MOCK vs
LIVE). Anything else is non-determinism the audit log has to show rather than
argue about. The comparison lists, per opportunity, what each run proposed and
which factors fired, and attributes a difference to a recorded version change
where one exists -- or labels it unattributed, which is the finding.
"""

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.confidence_event import ConfidenceEvent
from app.db.models.opportunity import Opportunity
from app.db.models.proposal import Proposal
from app.db.models.rubric_version import RubricVersion
from app.db.models.run import Run


@dataclass
class RowDiff:
    opportunity_id: str
    project: str
    a_proposed: float | None
    b_proposed: float | None
    a_rules: list[str]
    b_rules: list[str]
    same: bool
    attributed_to: list[str] = field(default_factory=list)


@dataclass
class RunComparison:
    run_a: str
    run_b: str
    stamps_a: dict
    stamps_b: dict
    stamp_differences: list[str]
    rows: list[RowDiff]
    identical: bool
    unattributed_differences: int


def _stamps(db: Session, run: Run) -> dict:
    version = db.get(RubricVersion, run.rubric_version_id)
    event = db.scalars(
        select(ConfidenceEvent).join(Proposal, ConfidenceEvent.proposal_id == Proposal.id)
        .where(Proposal.run_id == run.id, ConfidenceEvent.event_type == "proposal").limit(1)
    ).first()
    return {
        "rubric_version": version.label if version else run.rubric_version_id,
        "prompt_version": (event.prompt_version.split(";")[0] if event and event.prompt_version else None),
        "model_id": event.model_id if event else None,
        "mode": run.mode,
        "snapshot_id": run.snapshot_id,
    }


def compare_runs(db: Session, run_a_id: str, run_b_id: str) -> RunComparison:
    run_a, run_b = db.get(Run, run_a_id), db.get(Run, run_b_id)
    if run_a is None or run_b is None:
        raise KeyError("run not found")
    stamps_a, stamps_b = _stamps(db, run_a), _stamps(db, run_b)
    stamp_differences = [k for k in ("rubric_version", "prompt_version", "model_id", "mode", "snapshot_id")
                         if stamps_a.get(k) != stamps_b.get(k)]

    def proposals_for(run_id: str) -> dict[str, Proposal]:
        return {p.opportunity_id: p for p in db.scalars(
            select(Proposal).where(Proposal.run_id == run_id, Proposal.kind == "confidence")
        ).all()}

    pa, pb = proposals_for(run_a.id), proposals_for(run_b.id)
    rows: list[RowDiff] = []
    unattributed = 0
    for opp_id in sorted(set(pa) | set(pb)):
        opp = db.get(Opportunity, opp_id)
        a, b = pa.get(opp_id), pb.get(opp_id)
        a_rules = sorted(f.get("rule_id") or f["key"] for f in (a.factors if a else []) if f.get("applies") and f.get("accepted"))
        b_rules = sorted(f.get("rule_id") or f["key"] for f in (b.factors if b else []) if f.get("applies") and f.get("accepted"))
        a_val = round(a.proposed_confidence, 4) if a else None
        b_val = round(b.proposed_confidence, 4) if b else None
        same = a_val == b_val and a_rules == b_rules
        attributed = [] if same else list(stamp_differences)
        if not same and not attributed:
            unattributed += 1
        rows.append(RowDiff(opp_id, opp.project if opp else opp_id, a_val, b_val, a_rules, b_rules, same, attributed))
    return RunComparison(
        run_a=run_a.id, run_b=run_b.id, stamps_a=stamps_a, stamps_b=stamps_b,
        stamp_differences=stamp_differences, rows=rows,
        identical=all(r.same for r in rows), unattributed_differences=unattributed,
    )
