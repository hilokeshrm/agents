"""Pydantic request/response models for the opportunity intake form and API.
Mirrors the field map in docs/03-reference/Opportunity_Tracking_Agent_Tab_and_Field_Map.docx.
Direct UI entry is the primary intake path (see [[opptrack-intake-not-excel]]);
these schemas back that form first, with import/CRM sync mapping onto the same shape.
"""

from datetime import date

from pydantic import BaseModel, Field


class OpportunityCreate(BaseModel):
    external_id: str | None = None
    region: str
    customer: str
    end_customer: str
    project: str
    application: str | None = None  # V5
    product_line: str | None = None  # V6
    part_number: str
    design_status: str
    stage: str
    mp_date: date | None = None  # V10; mass-production start date
    eau_kpcs: float = Field(gt=0)
    unit_set: float | None = Field(default=None, gt=0)  # V12; optional -- feeds C3/C4 when present
    disty_asp: float = Field(gt=0)
    nre_charge_k: float | None = Field(default=None, ge=0)  # V29; one-off, never phased like silicon
    resale_asp: float | None = None
    # {"2025": [q1, q2, q3, q4], ...} units in Kpcs; the programme phasing profile (WBS 5.5)
    phasing_profile: dict[str, list[float]] | None = None
    confidence: float = Field(ge=0, le=1)
    # Required when design_status is Lost at intake (Matrix A: Lost is terminal
    # and needs a loss reason; the transition path enforces the same).
    loss_reason: str | None = None
    competitor_part: str | None = None
    owner: str
    evidence: str | None = None
    confidence_rationale: str


class OpportunityRead(OpportunityCreate):
    id: str
    external_id: str
    sales_revenue_k: float
    adjusted_revenue_k: float
    # Carried beside volume revenue, never inside it (WBS 3.5).
    nre_revenue_k: float
    nre_weighted_k: float
    # C3-C7 (app/calc/engine.py, WBS 5.2) -- None whenever unit_set/resale_asp
    # aren't provided, never a guessed value standing in for a real one.
    set_volume: float | None
    attach_rate: float | None
    channel_margin_usd: float | None
    channel_margin_pct: float | None
    # Advisory findings raised at intake (decision #62): the row was accepted,
    # and these say what it still lacks.
    intake_advisories: list[dict] = []
