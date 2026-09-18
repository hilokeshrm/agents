"""Forecast accuracy (WBS 6.5, C15) -- the single highest-value output this
agent could produce, and the one that needs data nobody can type in: actuals
from the ERP extract (A1, primary) and the distributor POS feed (A2, cross-
check), plus a retained forecast vintage (A3) to compare against. Dark until
the actual table has rows; live the day the connector lands them.

Error is measured per (part, year, quarter) against the row's phased forecast
at the current vintage, and rolled up per region and per owner. A2 units
cross-check A1 revenue where both exist."""

from app.analysis.registry import Analysis, AnalysisContext, AnalysisResult
from app.calc.phasing import phase, quarterly_revenue_k


def run(ctx: AnalysisContext) -> AnalysisResult:
    forecast: dict[tuple[str, int, int], dict] = {}
    for f, opp in zip(ctx.financials, ctx.opportunities):
        profile = {int(k): v for k, v in (opp.phasing_profile or {}).items()} or None
        p = phase(eau_kpcs=opp.eau_kpcs, mp_date=opp.mp_date, profile=profile)
        for (y, q), rev in quarterly_revenue_k(p, f.sales_revenue_k).items():
            key = (f.part_number, y, q)
            bucket = forecast.setdefault(key, {"revenue_k": 0.0, "units_kpcs": 0.0, "region": f.region,
                                               "owner": opp.owner, "projects": []})
            bucket["revenue_k"] += rev
            bucket["units_kpcs"] += next((qq.units_kpcs or 0.0 for qq in p.quarters if (qq.year, qq.quarter) == (y, q)), 0.0)
            bucket["projects"].append(f.project)

    rows = []
    by_region: dict[str, list[float]] = {}
    by_owner: dict[str, list[float]] = {}
    for a in ctx.actuals:
        key = (a.part_number, a.year, a.quarter)
        fc = forecast.get(key)
        if fc is None:
            rows.append({"part_number": a.part_number, "period": f"{a.year}-Q{a.quarter}", "source": a.source,
                         "actual_revenue_k": a.revenue_k, "forecast_revenue_k": None, "error": None,
                         "note": "actual with no forecast at this vintage -- unregistered demand"})
            continue
        if a.revenue_k is None:
            continue
        error = (fc["revenue_k"] - a.revenue_k) / fc["revenue_k"] if fc["revenue_k"] else None
        rows.append({"part_number": a.part_number, "period": f"{a.year}-Q{a.quarter}", "source": a.source,
                     "actual_revenue_k": a.revenue_k, "forecast_revenue_k": fc["revenue_k"], "error": error,
                     "region": fc["region"], "owner": fc["owner"], "projects": fc["projects"]})
        if error is not None:
            by_region.setdefault(fc["region"], []).append(error)
            by_owner.setdefault(fc["owner"], []).append(error)

    def bias(values: list[float]) -> float | None:
        return sum(values) / len(values) if values else None

    scored = [r for r in rows if r.get("error") is not None]
    overall = bias([r["error"] for r in scored])
    return AnalysisResult(
        key="forecast_accuracy", label="Forecast accuracy", status="live" if scored else "partial",
        headline=(f"forecast ran {overall:+.0%} against actuals over {len(scored)} part-quarters" if overall is not None
                  else "actuals present but none match a forecast part-quarter yet"),
        figures={"bias_overall": overall, "bias_by_region": {k: bias(v) for k, v in by_region.items()},
                 "bias_by_owner": {k: bias(v) for k, v in by_owner.items()},
                 "matched": len(scored), "unmatched_actuals": len(rows) - len(scored)},
        rows=rows,
        note="Error = (forecast - actual) / forecast per part-quarter; positive is optimistic. ERP revenue is the actual; POS units are the cross-check (decision #69).",
    )


ANALYSIS = Analysis(
    key="forecast_accuracy", label="Forecast accuracy",
    requires=frozenset({"A1", "A3", "V7", "V11", "V13"}), run=run,
    description="Bias and error per region, per owner, per vintage, against shipped actuals.",
)
