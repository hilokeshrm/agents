"""
Owner and region calibration (WBS 6.5, J-06, L5 memory) -- the quarterly batch.

For every opportunity whose latest design status is terminal (won: Mass
Production or Design Win; lost: Lost), the confidence the row carried when it
was last proposed or entered before resolution is compared with the outcome
(1.0 or 0.0). The mean signed difference per owner, in percentage points, is
that owner's bias; positive means optimistic. The standard deviation and the
sample size travel with it, because J-06 fires only beyond one standard
deviation and decision #70 wants at least two quarters of history before the
number is treated as reliable.

Rebuilt, never updated: each run writes fresh rows for the window. The
judgment layer reads the latest row per owner as a prior, never as a current
number.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from statistics import mean, pstdev

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.calibration import Calibration
from app.db.models.confidence_event import ConfidenceEvent
from app.db.models.opportunity import Opportunity
from app.db.models.state_history import StateHistory
from app.services.state_transitions import LOSS_VALUES, WIN_VALUES

MIN_SAMPLE = 5
RELIABLE_WINDOW_DAYS = 182  # two quarters, decision #70


@dataclass(frozen=True)
class ResolvedOutcome:
    opportunity_id: str
    owner: str
    region: str
    outcome: float               # 1.0 won, 0.0 lost
    confidence_before: float     # the confidence the row carried before it resolved
    resolved_at: datetime


def resolved_outcomes(db: Session, *, window_start: date | None = None) -> list[ResolvedOutcome]:
    events = db.scalars(select(StateHistory).where(StateHistory.field == "design_status").order_by(StateHistory.id)).all()
    latest: dict[str, StateHistory] = {}
    for e in events:
        latest[e.opportunity_id] = e
    out: list[ResolvedOutcome] = []
    for opp_id, e in latest.items():
        value = e.to_value.lower()
        if value in WIN_VALUES:
            outcome = 1.0
        elif value in LOSS_VALUES:
            outcome = 0.0
        else:
            continue
        if window_start and e.occurred_at.date() < window_start:
            continue
        opp = db.get(Opportunity, opp_id)
        if opp is None:
            continue
        # Confidence before resolution: the last confidence event before the
        # close, else the stored value (a row closed with no proposal history).
        prior_event = db.scalars(
            select(ConfidenceEvent).where(ConfidenceEvent.opportunity_id == opp_id,
                                          ConfidenceEvent.occurred_at <= e.occurred_at)
            .order_by(ConfidenceEvent.occurred_at.desc()).limit(1)
        ).first()
        before = prior_event.resulting_confidence if prior_event is not None else opp.confidence
        if value in LOSS_VALUES and before == 0.0 and prior_event is None:
            # A Lost row imported already zeroed carries no pre-resolution number.
            continue
        out.append(ResolvedOutcome(opp_id, opp.owner, opp.region, outcome, before, e.occurred_at))
    return out


def rebuild_calibration(db: Session, *, as_of: date | None = None, window_days: int = 730) -> list[Calibration]:
    """Writes one Calibration row per owner and per region with at least
    MIN_SAMPLE resolved outcomes in the window. Returns what it wrote."""
    as_of = as_of or date.today()
    window_start = as_of - timedelta(days=window_days)
    outcomes = resolved_outcomes(db, window_start=window_start)
    groups: dict[tuple[str, str | None, str | None], list[ResolvedOutcome]] = {}
    for o in outcomes:
        groups.setdefault(("owner", o.owner, None), []).append(o)
        groups.setdefault(("region", None, o.region), []).append(o)
    written: list[Calibration] = []
    for (_kind, owner, region), rows in groups.items():
        if len(rows) < MIN_SAMPLE:
            continue
        diffs = [(o.confidence_before - o.outcome) * 100.0 for o in rows]
        earliest = min(o.resolved_at for o in rows).date()
        span_ok = (as_of - earliest).days >= RELIABLE_WINDOW_DAYS
        row = Calibration(
            owner=owner, region=region, bias_pp=mean(diffs), sample_size=len(rows),
            window_start=window_start, window_end=as_of,
        )
        row.sd_pp = pstdev(diffs) if len(diffs) > 1 else 0.0
        row.reliable = span_ok
        db.add(row)
        written.append(row)
    db.flush()
    return written


def latest_by_owner(db: Session) -> dict[str, Calibration]:
    rows = db.scalars(select(Calibration).where(Calibration.owner.is_not(None)).order_by(Calibration.computed_at)).all()
    return {r.owner: r for r in rows}
