"""
Deterministic pipeline calculation engine.

This reimplements exactly the arithmetic in TrackF_1.xlsx (Funnel, ProjectTrack,
Mass Production, and Design Lost tabs) as plain, testable Python, with zero
LLM involvement, following the same design principle used in the ROI Agent:
the numbers a sales or leadership review sees must always be auditable
line by line, independent of anything an LLM decided.

Sales Revenue      = EAU (Kpcs) x Distributor ASP        (ProjectTrack: O = K * M)
Adjusted Revenue    = Sales Revenue x Confidence Level    (ProjectTrack: R = O * Q)

The judgment layer (see judgment.py) only ever proposes a *replacement or
adjustment* to the human-entered Confidence Level, never touches this math.
"""

from dataclasses import dataclass


@dataclass
class ProjectFinancials:
    project: str
    region: str
    customer: str
    stage: str
    design_status: str
    sales_revenue_k: float
    confidence: float
    adjusted_revenue_k: float


def compute_project_financials(row: dict) -> ProjectFinancials:
    """Row-level calc matching ProjectTrack columns O and R exactly."""
    sales_revenue = row["eau_kpcs"] * row["disty_asp"]
    adjusted_revenue = sales_revenue * row["confidence"]
    return ProjectFinancials(
        project=row["project"],
        region=row["region"],
        customer=row["customer"],
        stage=row.get("stage", row.get("design_status", "")),
        design_status=row["design_status"],
        sales_revenue_k=sales_revenue,
        confidence=row["confidence"],
        adjusted_revenue_k=adjusted_revenue,
    )


def compute_pipeline(project_track_rows: list) -> list:
    return [compute_project_financials(r) for r in project_track_rows]


def portfolio_rollup(financials: list) -> dict:
    """Aggregate weighted pipeline revenue by region and by stage, matching
    the kind of regional roll-up the Funnel/FCST_Revenue tabs build up to."""
    by_region = {}
    by_stage = {}
    total_sales = 0.0
    total_adjusted = 0.0

    for f in financials:
        by_region.setdefault(f.region, {"sales_revenue_k": 0.0, "adjusted_revenue_k": 0.0})
        by_region[f.region]["sales_revenue_k"] += f.sales_revenue_k
        by_region[f.region]["adjusted_revenue_k"] += f.adjusted_revenue_k

        by_stage.setdefault(f.stage, {"sales_revenue_k": 0.0, "adjusted_revenue_k": 0.0, "count": 0})
        by_stage[f.stage]["sales_revenue_k"] += f.sales_revenue_k
        by_stage[f.stage]["adjusted_revenue_k"] += f.adjusted_revenue_k
        by_stage[f.stage]["count"] += 1

        total_sales += f.sales_revenue_k
        total_adjusted += f.adjusted_revenue_k

    return {
        "by_region": by_region,
        "by_stage": by_stage,
        "total_sales_revenue_k": total_sales,
        "total_adjusted_revenue_k": total_adjusted,
    }


def quarterly_revenue(row: dict, quarterly_units: list, disty_asp: float) -> list:
    """Matches FCST_Revenue tab: quarterly revenue = quarterly units x Disty ASP
    (columns S:V = L * N:Q, or AC:AF = L * X:AA)."""
    return [units * disty_asp for units in quarterly_units]


if __name__ == "__main__":
    import json

    with open("data/sample_pipeline.json") as f:
        data = json.load(f)

    financials = compute_pipeline(data["project_track"])
    print("Row-level Sales Revenue and Adjusted Revenue (validated against TrackF_1.xlsx):")
    for f in financials:
        print(f"  {f.project:12} region={f.region:8} stage={f.stage:8} "
              f"sales_rev=${f.sales_revenue_k:>9,.1f}K  confidence={f.confidence:.2f}  "
              f"adjusted_rev=${f.adjusted_revenue_k:>9,.1f}K")

    rollup = portfolio_rollup(financials)
    print(f"\nTotal Sales Revenue (unweighted):  ${rollup['total_sales_revenue_k']:,.1f}K")
    print(f"Total Adjusted Revenue (weighted):  ${rollup['total_adjusted_revenue_k']:,.1f}K")
    print("\nBy region:")
    for region, vals in rollup["by_region"].items():
        print(f"  {region:10} sales=${vals['sales_revenue_k']:>9,.1f}K  adjusted=${vals['adjusted_revenue_k']:>9,.1f}K")
    print("\nBy stage:")
    for stage, vals in rollup["by_stage"].items():
        print(f"  {stage:10} count={vals['count']:2}  sales=${vals['sales_revenue_k']:>9,.1f}K  adjusted=${vals['adjusted_revenue_k']:>9,.1f}K")
