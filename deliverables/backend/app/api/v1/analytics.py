"""
Analytics computed from the state_history stream (WBS 9.2 done-when: win rate
computed from the stream, not estimated). Kept separate from app/analysis/registry.py
(WBS 6.0), which is deterministic reporting over the calc engine's figures -- this
is reporting over the event stream, a narrower and earlier-available thing.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.state_history import WinRateRead
from app.services.state_transitions import win_rate

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/win-rate", response_model=WinRateRead)
def get_win_rate(
    owner: str | None = None, region: str | None = None, db: Session = Depends(get_db)
) -> WinRateRead:
    return win_rate(db, owner=owner, region=region)
