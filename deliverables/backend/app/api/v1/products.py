"""
Products (WBS-adjacent, added for the UI build): not a stored entity, and the
same aggregation C7 (app/calc/engine.py's part_level_demand) already computes,
extended here with pricing pulled from whichever opportunity on that part
actually carries Disty ASP / Resale ASP -- "Aggregates unit demand across every
socket using the same part number" (docs/03-reference/
Opportunity_Tracking_Agent_Tab_and_Field_Map.docx, Part# column note).
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.opportunities import _to_read_model
from app.db.models.opportunity import Opportunity
from app.db.session import get_db
from app.schemas.rollup import ProductDetail, ProductSummary

router = APIRouter(prefix="/products", tags=["products"])


def _summarize(part_number: str, opps: list[Opportunity]) -> ProductSummary:
    reads = [_to_read_model(o) for o in opps]
    disty_asp = next((o.disty_asp for o in opps if o.disty_asp is not None), None)
    resale_asp = next((o.resale_asp for o in opps if o.resale_asp is not None), None)
    margin_pct = ((resale_asp - disty_asp) / resale_asp) if (disty_asp and resale_asp) else None
    return ProductSummary(
        part_number=part_number,
        product_line=next((o.product_line for o in opps if o.product_line), None),
        application=next((o.application for o in opps if o.application), None),
        disty_asp=disty_asp,
        resale_asp=resale_asp,
        margin_pct=margin_pct,
        opportunity_count=len(opps),
        pipeline_k=sum(r.adjusted_revenue_k for r in reads),
        combined_eau_kpcs=sum(o.eau_kpcs for o in opps),
    )


@router.get("", response_model=list[ProductSummary])
def list_products(db: Session = Depends(get_db)) -> list[ProductSummary]:
    all_opps = list(db.scalars(select(Opportunity)).all())
    by_part: dict[str, list[Opportunity]] = {}
    for opp in all_opps:
        by_part.setdefault(opp.part_number, []).append(opp)
    return [_summarize(part, opps) for part, opps in sorted(by_part.items())]


@router.get("/{part_number}", response_model=ProductDetail)
def get_product(part_number: str, db: Session = Depends(get_db)) -> ProductDetail:
    opps = list(db.scalars(select(Opportunity).where(Opportunity.part_number == part_number)).all())
    if not opps:
        raise HTTPException(status_code=404, detail="Product not found")
    summary = _summarize(part_number, opps)
    return ProductDetail(**summary.model_dump(), opportunities=[_to_read_model(o) for o in opps])
