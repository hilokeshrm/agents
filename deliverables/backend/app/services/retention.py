"""
Retention and deletion policy (WBS 9.7, R4 retention, decisions #64, #83-#85).

- L1 episodic (snapshots, runs, confidence events, state history, owner
  history): immutable for seven years. Enforced by app/db/immutable.py at the
  ORM; this job only reports counts and the oldest row, it never deletes.
- L3 semantic (memory_chunk): rolls off after eight quarters unless preserved.
- Accounts: deleted accounts are anonymised, never removed (app/api/v1/users.py).

`enforce_retention` is the scheduled job: expire what should expire, report
what is protected, and refuse to touch anything else.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models.app_user import AppUser
from app.db.models.confidence_event import ConfidenceEvent
from app.db.models.memory_chunk import MemoryChunk
from app.db.models.snapshot import Snapshot
from app.db.models.state_history import StateHistory
from app.memory import expire

SEVEN_YEARS = timedelta(days=7 * 365)
EIGHT_QUARTERS = timedelta(days=8 * 91)


@dataclass
class RetentionReport:
    semantic_expired: int
    semantic_live: int
    episodic_rows: int
    episodic_oldest: str | None
    episodic_within_policy: bool
    anonymised_accounts: int
    policy: dict


def enforce_retention(db: Session, *, now: datetime | None = None) -> RetentionReport:
    now = now or datetime.now(timezone.utc)
    expired = expire(db, now=now)
    live = db.scalar(select(func.count(MemoryChunk.id))) or 0
    counts = 0
    oldest: datetime | None = None
    for model, col in ((ConfidenceEvent, ConfidenceEvent.occurred_at), (StateHistory, StateHistory.occurred_at),
                       (Snapshot, Snapshot.captured_at)):
        counts += db.scalar(select(func.count(model.id))) or 0
        first = db.scalar(select(func.min(col)))
        if first is not None:
            first = first if first.tzinfo else first.replace(tzinfo=timezone.utc)
            oldest = first if oldest is None or first < oldest else oldest
    anonymised = db.scalar(select(func.count(AppUser.id)).where(AppUser.anonymised_at.is_not(None))) or 0
    return RetentionReport(
        semantic_expired=expired, semantic_live=live, episodic_rows=counts,
        episodic_oldest=oldest.isoformat() if oldest else None,
        episodic_within_policy=(oldest is None or now - oldest <= SEVEN_YEARS),
        anonymised_accounts=anonymised,
        policy={"episodic": "immutable, 7 years, never deleted by this job",
                "semantic": "expires after 8 quarters unless preserved",
                "accounts": "anonymised on delete, decisions kept"},
    )
