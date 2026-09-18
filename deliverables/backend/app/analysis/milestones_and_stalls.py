"""Milestone and stall detection (WBS 6.2, 8.5; C14, J-09, J-10).

Milestones: PPAP, ES, Design Review and SoP dates parsed from the row's free
text (evidence, rationale), each citing the source substring; overdue ones are
listed. Stalls: days in the current stage from the state_history stream
against the median for that stage across the portfolio. Decision #75: until
better history exists, a stall is more than two median stage durations; the
specification's 1.5x applies once a real population exists (>= 10 resolved
stage exits). With no history the stall half reports partial, not a guess.
"""

from statistics import median

from app.analysis.registry import Analysis, AnalysisContext, AnalysisResult
from app.intake.milestones import extract_milestones
from app.judgment.matrix_b import STALL_MULTIPLE

PROVISIONAL_STALL_MULTIPLE = 2.0
POPULATION_FOR_SPEC_MULTIPLE = 10


def stage_durations(db) -> dict[str, list[float]]:
    """Completed stage visits per stage, in days, from the stream: each stage
    transition closes the previous stage's visit."""
    from sqlalchemy import select

    from app.db.models.state_history import StateHistory

    events = db.scalars(select(StateHistory).where(StateHistory.field == "stage").order_by(StateHistory.opportunity_id, StateHistory.id)).all()
    durations: dict[str, list[float]] = {}
    last: dict[str, StateHistory] = {}
    for e in events:
        prev = last.get(e.opportunity_id)
        if prev is not None:
            days = (e.occurred_at - prev.occurred_at).total_seconds() / 86400.0
            durations.setdefault(prev.to_value, []).append(days)
        last[e.opportunity_id] = e
    return durations


def days_in_stage(db, opp, as_of) -> float | None:
    from datetime import datetime, time, timezone

    from sqlalchemy import select

    from app.db.models.state_history import StateHistory

    latest = db.scalars(
        select(StateHistory).where(StateHistory.opportunity_id == opp.id, StateHistory.field == "stage")
        .order_by(StateHistory.id.desc()).limit(1)
    ).first()
    since = latest.occurred_at if latest is not None else opp.created_at
    if since is None:
        return None
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    now = datetime.combine(as_of, time.min, tzinfo=timezone.utc)
    return max(0.0, (now - since).total_seconds() / 86400.0)


def run(ctx: AnalysisContext) -> AnalysisResult:
    rows = []
    overdue_total = 0
    for opp in ctx.opportunities:
        text = " ".join(filter(None, [opp.evidence, opp.confidence_rationale]))
        events = extract_milestones(text, ctx.as_of)
        overdue = [e for e in events if e.overdue]
        overdue_total += len(overdue)
        if events:
            rows.append({
                "project": opp.project, "opportunity_id": opp.id, "kind": "milestone",
                "milestones": [{"milestone": e.milestone, "source_substring": e.source_substring,
                                "date": e.parsed_date.isoformat() if e.parsed_date else None, "overdue": e.overdue}
                               for e in events],
                "overdue": len(overdue),
            })

    status = "live"
    stalls = []
    stall_note = ""
    if ctx.db is not None and "H1" in ctx.available:
        durations = stage_durations(ctx.db)
        population = sum(len(v) for v in durations.values())
        multiple = STALL_MULTIPLE if population >= POPULATION_FOR_SPEC_MULTIPLE else PROVISIONAL_STALL_MULTIPLE
        medians = {s: median(v) for s, v in durations.items() if v}
        for opp in ctx.opportunities:
            days = days_in_stage(ctx.db, opp, ctx.as_of)
            med = medians.get(opp.stage)
            if days is None or med is None or med <= 0:
                continue
            if days > multiple * med:
                stalls.append({"project": opp.project, "opportunity_id": opp.id, "kind": "stall", "stage": opp.stage,
                               "days_in_stage": round(days, 1), "stage_median_days": round(med, 1),
                               "multiple": round(days / med, 2), "threshold_multiple": multiple})
        stall_note = (f"stall threshold {multiple}x the stage median over {population} completed stage visits"
                      + (" (provisional 2x until 10 visits exist, decision #75)" if multiple == PROVISIONAL_STALL_MULTIPLE else ""))
        if not medians:
            status = "partial"
            stall_note = "no completed stage visit yet, so no median to compare against; milestones only"
    else:
        status = "partial"
        stall_note = "no state history in this run (H1 absent); milestones only"
    rows.extend(stalls)
    return AnalysisResult(
        key="milestones_and_stalls", label="Milestone and stall detection", status=status,
        headline=f"{overdue_total} overdue milestone(s), {len(stalls)} stalled row(s)",
        figures={"overdue_milestones": overdue_total, "stalled_rows": len(stalls)},
        rows=rows, note=stall_note,
    )


ANALYSIS = Analysis(
    key="milestones_and_stalls", label="Milestone and stall detection",
    requires=frozenset({"V9", "V19"}), run=run,
    description="Overdue PPAP/ES/Design Review/SoP dates from the row's own text; rows sitting past their stage's median.",
)
