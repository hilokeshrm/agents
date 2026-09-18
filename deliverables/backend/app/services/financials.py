"""
One place that turns an Opportunity row into the dict app/calc/engine.py expects.

Before this module, seven call sites (the read model, the review console, the
rubric impact preview, both scenario paths, the assistant and the judgment run)
each built that dict by hand. They had already drifted: none of them passed
`end_customer` or `product_line`, so every roll-up grouped by those dimensions
reported "Unspecified" for the whole portfolio, and adding a field meant editing
seven places and hoping. A field the engine reads should be listed once.

The ORM stays on this side of the boundary: the engine takes plain dicts and
knows nothing about SQLAlchemy, which is what lets it be tested against the
workbook without a database.
"""

from app.calc.engine import ProjectFinancials, compute_project_financials
from app.db.models.opportunity import Opportunity


def engine_row(opportunity: Opportunity, confidence: float | None = None) -> dict:
    """The engine's input for one opportunity. `confidence` overrides the stored
    value for scenario and proposal previews -- the base case and the calibrated
    case must be the same function called twice, which only holds if they are
    also given the same shape of input."""
    return {
        "project": opportunity.project,
        "region": opportunity.region,
        "customer": opportunity.customer,
        "end_customer": opportunity.end_customer,
        "product_line": opportunity.product_line,
        "design_status": opportunity.design_status,
        "stage": opportunity.stage,
        "part_number": opportunity.part_number,
        "eau_kpcs": opportunity.eau_kpcs,
        "unit_set": opportunity.unit_set,
        "disty_asp": opportunity.disty_asp,
        "resale_asp": opportunity.resale_asp,
        "nre_charge_k": opportunity.nre_charge_k,
        "confidence": opportunity.confidence if confidence is None else confidence,
    }


def financials_for(opportunity: Opportunity, confidence: float | None = None) -> ProjectFinancials:
    return compute_project_financials(engine_row(opportunity, confidence))


def adjusted_revenue_k(opportunity: Opportunity, confidence: float | None = None) -> float:
    """Volume revenue only. NRE is on the same ProjectFinancials object under
    `nre_revenue_k` and is deliberately not added in here -- a caller that wants
    both has to say so."""
    return financials_for(opportunity, confidence).adjusted_revenue_k
