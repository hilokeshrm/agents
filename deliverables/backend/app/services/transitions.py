"""
Lifecycle transition proposals (WBS 8.3, decisions #36-#37).

David Nam answered "auto-enter confidence" and "auto-move records" as two
separate questions. Read together they meant nobody signs off before an
opportunity is closed as lost or promoted to mass production. The decision
register resolves it: the agent does not move a record. It raises a
*transition proposal* -- the same queue, the same reviewer, the same
separation of duties -- and a person with the close grant approves it, at
which point record_transition writes the state_history row exactly as a
manual move would. A close therefore cannot happen without the sign-off the
policy requires, whether the agent or a person started it.

Detection is deliberately narrow. Two signals are strong enough to propose on:

- Mass Production: a Design Win at PVT whose mass-production date has passed.
  The row says it is won and the date says it has started; what is missing is
  a person confirming it.
- Lost: the row's own evidence says so -- "lost", "design lost", "awarded to
  <competitor>". The agent proposes; the reviewer supplies the loss reason
  code on approval, because the reason is the one thing the agent must not
  guess (WBS 8.4).

Anything weaker (confidence at the floor, a stalled stage) is a judgment
factor, not a lifecycle signal, and stays in the confidence proposal.
"""

import re
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.opportunity import Opportunity
from app.db.models.proposal import Proposal
from app.db.models.rubric_version import RubricVersion

MASS_PRODUCTION = "Mass Production"
LOST = "Lost"
TERMINAL = frozenset({MASS_PRODUCTION, LOST})

_LOST_SIGNAL = re.compile(r"\b(design\s+lost|lost\s+to\b|awarded\s+to\b|we\s+lost\b|lost\s+the\s+socket)", re.I)


@dataclass(frozen=True)
class TransitionCandidate:
    opportunity: Opportunity
    to_value: str
    reason: str
    evidence_quote: str


def detect_candidates(rows: list[Opportunity], *, as_of: date) -> list[TransitionCandidate]:
    out: list[TransitionCandidate] = []
    for opp in rows:
        if opp.design_status in TERMINAL:
            continue
        if opp.design_status == "Design Win" and opp.stage == "PVT" and opp.mp_date and opp.mp_date <= as_of:
            out.append(TransitionCandidate(
                opp, MASS_PRODUCTION,
                reason=f"Design Win at PVT with M/P date {opp.mp_date.isoformat()} on or before {as_of.isoformat()}",
                evidence_quote=f"mp_date: {opp.mp_date.isoformat()}",
            ))
            continue
        text = " ".join(filter(None, [opp.evidence, opp.confidence_rationale]))
        m = _LOST_SIGNAL.search(text)
        if m:
            out.append(TransitionCandidate(
                opp, LOST,
                reason="the row's own evidence says the socket was lost",
                evidence_quote=m.group(0),
            ))
    return out


def open_transition_ids(db: Session) -> set[str]:
    return set(db.scalars(
        select(Proposal.opportunity_id).where(Proposal.kind == "transition", Proposal.status == "pending")
    ).all())


def propose_transition(
    db: Session, candidate: TransitionCandidate, version: RubricVersion, *, run_id: str | None, actor: str = "agent"
) -> Proposal:
    opp = candidate.opportunity
    proposal = Proposal(
        opportunity_id=opp.id,
        rubric_version_id=version.id,
        run_id=run_id,
        kind="transition",
        transition={
            "field": "design_status",
            "from_value": opp.design_status,
            "to_value": candidate.to_value,
            "reason": candidate.reason,
            "evidence_quote": candidate.evidence_quote,
            "requires_reason_code": candidate.to_value == LOST,
        },
        base_confidence=opp.confidence,
        proposed_confidence=opp.confidence,   # a transition proposal moves no number
        factors=[],
        flags={},
        status="pending",
        band_crossing=False,
    )
    db.add(proposal)
    db.flush()
    return proposal
