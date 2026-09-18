"""Stage mix and pipeline health (WBS 6.2): how much weighted revenue sits at
each funnel stage, and whether the mix is top-heavy with early-stage optimism.
On the specification's nine rows: 62% of the weighted pipeline at EVT, 86% of
the raw pipeline at Concept or EVT."""

from app.analysis.registry import Analysis, AnalysisContext, AnalysisResult
from app.judgment.matrix_b import EARLY_STAGES, STAGE_ORDER

TOP_HEAVY_SHARE = 0.50


def run(ctx: AnalysisContext) -> AnalysisResult:
    by_stage: dict[str, dict] = {s: {"count": 0, "sales_k": 0.0, "adjusted_k": 0.0, "rows": []} for s in STAGE_ORDER}
    for f in ctx.financials:
        bucket = by_stage.setdefault(f.stage, {"count": 0, "sales_k": 0.0, "adjusted_k": 0.0, "rows": []})
        bucket["count"] += 1
        bucket["sales_k"] += f.sales_revenue_k
        bucket["adjusted_k"] += f.adjusted_revenue_k
        bucket["rows"].append(f.project)
    total_adj = sum(b["adjusted_k"] for b in by_stage.values())
    total_sales = sum(b["sales_k"] for b in by_stage.values())
    early_adj = sum(b["adjusted_k"] for s, b in by_stage.items() if s in EARLY_STAGES)
    early_sales = sum(b["sales_k"] for s, b in by_stage.items() if s in EARLY_STAGES)
    early_share = early_adj / total_adj if total_adj else 0.0
    raw_early_share = early_sales / total_sales if total_sales else 0.0
    rows = [
        {"stage": s, "count": b["count"], "sales_revenue_k": b["sales_k"], "adjusted_revenue_k": b["adjusted_k"],
         "share_of_weighted": (b["adjusted_k"] / total_adj) if total_adj else 0.0,
         "effective_confidence": (b["adjusted_k"] / b["sales_k"]) if b["sales_k"] else None,
         "projects": b["rows"]}
        for s, b in by_stage.items() if b["count"]
    ]
    top_heavy = early_share > TOP_HEAVY_SHARE
    return AnalysisResult(
        key="stage_mix", label="Stage mix and pipeline health",
        status="live" if ctx.financials else "partial",
        headline=(f"{early_share:.0%} of the weighted pipeline has not reached DVT"
                  + (" -- top-heavy" if top_heavy else "")),
        figures={"weighted_total_k": total_adj, "raw_total_k": total_sales, "early_share_of_weighted": early_share,
                 "early_share_of_raw": raw_early_share, "top_heavy": top_heavy, "excluded_rows": ctx.excluded_count},
        rows=rows,
        note="Weighted = C2 (Sales Revenue x Confidence). Early = Concept or EVT. Blocking rows are excluded and counted.",
    )


ANALYSIS = Analysis(
    key="stage_mix", label="Stage mix and pipeline health",
    requires=frozenset({"V8", "V9", "V11", "V13", "V17"}), run=run,
    description="Weighted revenue by funnel stage; flags a mix top-heavy with early-stage optimism.",
)
