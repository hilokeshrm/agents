"""Response shapes for the computed rollup endpoints (accounts, products,
reports, dashboards). None of these back a stored table -- every one of them is
grouped live from Opportunity rows, recomputed on each request the same way
app/calc/engine.py's portfolio_rollup already works."""

from pydantic import BaseModel


class AccountSummary(BaseModel):
    name: str
    end_customers: list[str]
    regions: list[str]
    opportunity_count: int
    open_pipeline_k: float
    closed_won_k: float


class AccountDetail(AccountSummary):
    opportunities: list  # list[OpportunityRead], typed loosely to avoid a schema-module cycle
    pipeline_by_product_line: dict[str, float]
    weighted_k: float
    parts_in_play: int


class ProductSummary(BaseModel):
    part_number: str
    product_line: str | None
    application: str | None
    disty_asp: float | None
    resale_asp: float | None
    margin_pct: float | None
    opportunity_count: int
    pipeline_k: float
    combined_eau_kpcs: float


class ProductDetail(ProductSummary):
    opportunities: list


class ReportRow(BaseModel):
    group: str
    extra: str | None = None
    opportunity_count: int
    total_amount_k: float
    opportunities: list


class ReportResult(BaseModel):
    report_id: str
    name: str
    groups: list[ReportRow]
    grand_total_k: float
    record_count: int


class DashboardSummary(BaseModel):
    total_pipeline_k: float
    open_pipeline_k: float
    weighted_forecast_k: float
    closed_won_k: float
    opportunity_count: int
    total_nre_revenue_k: float = 0.0  # beside the volume figures, never inside them
    funnel_by_design_status: list[dict]
    pipeline_by_product_line: dict[str, float]
    pipeline_by_mp_year: dict[str, float]
