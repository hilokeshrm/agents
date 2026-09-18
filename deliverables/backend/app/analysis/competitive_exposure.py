"""Competitive exposure (WBS 6.2): which sockets have a named rival and how
much weighted revenue is exposed per competitor part. Partial on the
workbook's own rows because Competitor Part# is blank on every ProjectTrack
row; live the moment the column is populated at intake."""

from app.analysis.registry import Analysis, AnalysisContext, AnalysisResult


def run(ctx: AnalysisContext) -> AnalysisResult:
    exposed: dict[str, dict] = {}
    rows = []
    total = sum(f.adjusted_revenue_k for f in ctx.financials)
    for f, opp in zip(ctx.financials, ctx.opportunities):
        part = (opp.competitor_part or "").strip()
        if not part or part.upper() == "TBD":
            continue
        for rival in [p.strip() for p in part.replace("\n", ",").split(",") if p.strip()]:
            bucket = exposed.setdefault(rival, {"competitor_part": rival, "sockets": [], "exposed_k": 0.0})
            bucket["sockets"].append(f.project)
            bucket["exposed_k"] += f.adjusted_revenue_k
        rows.append({"project": f.project, "opportunity_id": opp.id, "competitor_part": part,
                     "adjusted_revenue_k": f.adjusted_revenue_k, "stage": f.stage, "design_status": f.design_status})
    exposed_total = sum(r["adjusted_revenue_k"] for r in rows)
    named = len(rows)
    status = "live" if named else "partial"
    return AnalysisResult(
        key="competitive_exposure", label="Competitive exposure", status=status,
        headline=(f"{named} socket(s) with a named rival; ${exposed_total:,.0f}K ({exposed_total / total:.0%}) of the weighted pipeline exposed"
                  if total and named else "no row names a competitor part"),
        figures={"sockets_with_rival": named, "exposed_k": exposed_total,
                 "exposed_share": (exposed_total / total) if total else 0.0,
                 "by_competitor": sorted(exposed.values(), key=lambda b: -b["exposed_k"])},
        rows=rows,
        note="Competitor Part# is populated on Funnel and blank on ProjectTrack in the workbook; capture it at intake to make this live.",
    )


ANALYSIS = Analysis(
    key="competitive_exposure", label="Competitive exposure",
    requires=frozenset({"V16", "V7", "V11", "V13", "V17"}), run=run,
    description="Which sockets have a named rival and how much revenue is exposed per competitor part.",
)
