"""Coverage against target (WBS 6.4, C13, decisions #67-#68): weighted pipeline
divided by Finance's target, by region and period. Requires G1/G2 -- rows in
the target table. Dark until Finance enters them, and it says so; Sheet1's
Projection/Stretch was never a target (a 4.4x "coverage" against it proved
the two numbers measure different things)."""

from app.analysis.registry import Analysis, AnalysisContext, AnalysisResult
from app.calc.phasing import phase


def _period_keys(opp) -> set[str]:
    """The periods a row's weighted revenue falls in, from its phasing: the
    year and the year-quarter of every phased quarter, or nothing when unphased."""
    profile = {int(k): v for k, v in (opp.phasing_profile or {}).items()} or None
    p = phase(eau_kpcs=opp.eau_kpcs, mp_date=opp.mp_date, profile=profile)
    keys: dict[str, float] = {}
    for q in p.quarters:
        keys[str(q.year)] = keys.get(str(q.year), 0.0) + q.fraction
        keys[f"{q.year}-Q{q.quarter}"] = keys.get(f"{q.year}-Q{q.quarter}", 0.0) + q.fraction
    return keys


def run(ctx: AnalysisContext) -> AnalysisResult:
    weighted: dict[tuple[str, str], float] = {}
    for f, opp in zip(ctx.financials, ctx.opportunities):
        for period, fraction in _period_keys(opp).items():
            for region in (f.region, "*"):
                weighted[(region, period)] = weighted.get((region, period), 0.0) + f.adjusted_revenue_k * fraction
    rows = []
    for t in ctx.targets:
        pipeline = weighted.get((t.region, t.period), 0.0)
        rows.append({"region": t.region, "period": t.period, "target_k": t.amount_k, "weighted_pipeline_k": pipeline,
                     "coverage": (pipeline / t.amount_k) if t.amount_k else None,
                     "gap_k": pipeline - t.amount_k})
    short = [r for r in rows if r["coverage"] is not None and r["coverage"] < 1.0]
    return AnalysisResult(
        key="coverage", label="Coverage against target", status="live",
        headline=f"{len(rows)} target(s); {len(short)} under-covered",
        figures={"targets": len(rows), "under_covered": [f"{r['region']} {r['period']}" for r in short]},
        rows=sorted(rows, key=lambda r: (r["region"], r["period"])),
        note="Coverage = weighted pipeline in the period / Finance's target (decision #68). Pipeline is phased into periods by the WBS 5.5 rule; unphased rows count in no period.",
    )


ANALYSIS = Analysis(
    key="coverage", label="Coverage against target",
    requires=frozenset({"G1", "G2", "V1", "V11", "V13", "V17"}), run=run,
    description="Whether the bottom-up weighted pipeline supports the top-down commitment, by region and period.",
)
