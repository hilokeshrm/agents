"""Margin and price (WBS 6.2, C5/C6): channel margin per row now -- Resale ASP
minus Distributor ASP, two figures the workbook collects on every row and
feeds to no formula -- and a profit-ranked pipeline once standard cost (C1)
exists. Without cost the gross-margin half reports partial, by name."""

from app.analysis.registry import Analysis, AnalysisContext, AnalysisResult


def run(ctx: AnalysisContext) -> AnalysisResult:
    rows = []
    for f in ctx.financials:
        if f.channel_margin_usd is None:
            rows.append({"project": f.project, "channel_margin_usd": None, "channel_margin_pct": None,
                         "margin_on_row_k": None, "note": "no Resale ASP on the row"})
            continue
        rows.append({
            "project": f.project, "part_number": f.part_number, "disty_asp": f.sales_revenue_k / f.eau_kpcs if f.eau_kpcs else None,
            "channel_margin_usd": f.channel_margin_usd, "channel_margin_pct": f.channel_margin_pct,
            "margin_on_row_k": f.channel_margin_usd * f.eau_kpcs,
            "formula_derived": abs((f.channel_margin_pct or 0) - 0.025) < 1e-6,
        })
    priced = [r for r in rows if r["channel_margin_usd"] is not None]
    priced.sort(key=lambda r: -(r["margin_on_row_k"] or 0))
    total_margin = sum(r["margin_on_row_k"] for r in priced)
    anomalies = [r for r in priced if r["channel_margin_pct"] < 0 or r["channel_margin_pct"] > 0.15]
    gross_available = "C1" in ctx.available
    return AnalysisResult(
        key="channel_margin", label="Margin and price",
        status="live" if gross_available else "partial",
        headline=f"${total_margin:,.0f}K channel margin across {len(priced)} priced rows; {len(anomalies)} outside the 0-15% band",
        figures={"total_channel_margin_k": total_margin, "priced_rows": len(priced),
                 "unpriced_rows": len(rows) - len(priced), "anomalies": [r["project"] for r in anomalies],
                 "gross_margin": "needs C1 standard cost" if not gross_available else "available"},
        rows=priced + [r for r in rows if r["channel_margin_usd"] is None],
        note="Channel margin = Resale ASP - Distributor ASP. A 2.5% margin is the Resale x 0.975 formula on three Funnel rows, not an anomaly. Gross margin waits on C1 (standard cost).",
    )


ANALYSIS = Analysis(
    key="channel_margin", label="Margin and price",
    requires=frozenset({"V13", "V14", "V11"}), run=run,
    description="Channel margin per row; profit-ranked pipeline once standard cost exists.",
)
