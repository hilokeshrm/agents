"""
Request/response models for the review console (WBS 10.5) and the runs & audit
viewer (WBS 10.9).

A proposal leaves this API as the whole decision, not a number: the factors that
fired, the ones a guard rejected and why, the ones that could not be assessed at
all, and the revenue both before and after. The screen is a rendering of these
fields; it computes nothing of its own.
"""

from datetime import datetime

from pydantic import BaseModel


class FactorRead(BaseModel):
    rule_id: str | None = None      # Matrix B id, J-01..J-13
    key: str
    applies: bool
    confidence_adjustment_pct: float
    quote: str = ""                 # verbatim from the evidence bundle
    rationale: str
    confidence: float
    accepted: bool
    guard: str | None = None        # the guard that rejected or clipped it
    detail: str | None = None
    clipped_from: float | None = None


class ProposalRead(BaseModel):
    id: str
    opportunity_id: str
    run_id: str | None
    rubric_version_id: str
    rubric_version_label: str | None
    status: str
    base_confidence: float
    proposed_confidence: float
    band_crossing: bool | None
    kind: str = "confidence"
    transition: dict | None = None
    flags: dict = {}
    factors: list[FactorRead]
    created_at: datetime
    resolved_at: datetime | None
    resolved_by: str | None

    # Row context, so the queue is readable without a second call per proposal.
    project: str
    customer: str
    region: str
    owner: str
    design_status: str
    stage: str
    part_number: str
    matrix_a_baseline: float | None  # null when the Matrix A cell is unset (WBS 1.1 Q1)
    base_adjusted_revenue_k: float
    proposed_adjusted_revenue_k: float

    # Whether the caller may act on this row, decided by the same rules the API
    # enforces -- so the interface hides a control the API would refuse anyway,
    # rather than the two disagreeing.
    actionable: bool
    blocked_reason: str | None


class ProposalResolve(BaseModel):
    action: str  # approve | reject | override
    value: float | None = None
    reason_code: str | None = None  # required for an override (override_reason) and a rejection (rejection_reason)
    note: str | None = None
    # WBS 8.7: which factors the reviewer disagreed with. Rule ids (J-05) or
    # keys; aggregated per rule on the rubric admin screen.
    rejected_factors: list[str] | None = None


class RunStepRead(BaseModel):
    n: int
    name: str
    lane: str    # deterministic | judgment | human
    status: str  # ran | skipped | failed
    detail: str


class RunRead(BaseModel):
    id: str
    kind: str
    status: str
    mode: str
    rubric_version_id: str
    rubric_version_label: str | None
    snapshot_id: str | None
    actor: str
    steps: list[RunStepRead]
    counts: dict
    error: str | None
    started_at: datetime
    finished_at: datetime | None


class RunCreate(BaseModel):
    opportunity_ids: list[str] | None = None


class AuditEventRead(BaseModel):
    """One row of the append-only audit feed. Sourced from three real tables --
    confidence_event, state_history and finding -- never from a log file."""

    at: datetime
    source: str  # confidence_event | state_history | finding
    kind: str
    opportunity_id: str | None
    project: str | None
    actor: str
    actor_role: str | None
    summary: str
    detail: str | None
    reason_code: str | None
    proposal_id: str | None
    run_id: str | None
