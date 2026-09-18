"""Concentration risk (WBS 6.2, C12): what a single loss would cost. Single-row,
single-customer, single-OEM, single-region and single-part dependency, with the
specification's triggers (25% of a region for one row, 40% of the portfolio for
one OEM). On the nine rows: Korea 81%, Ford 60%, Hermes 39%, AX01 40%."""

from app.analysis.registry import Analysis, AnalysisContext, AnalysisResult
from app.judgment.matrix_b import OEM_SHARE_OF_PORTFOLIO_TRIGGER, ROW_SHARE_OF_REGION_TRIGGER
from app.services.portfolio import concentration, portfolio_context

SUPPLY_RISK_PART_SHARE = 0.35


def run(ctx: AnalysisContext) -> AnalysisResult:
    conc = concentration(ctx.financials)
    shares = portfolio_context(ctx.financials)
    fired = []
    for f in ctx.financials:
        s = shares[f.project]
        if s.row_share_of_region is not None and s.row_share_of_region > ROW_SHARE_OF_REGION_TRIGGER:
            fired.append({"project": f.project, "cut": "row_share_of_region", "share": s.row_share_of_region,
                          "region": f.region, "adjusted_revenue_k": f.adjusted_revenue_k,
                          "what_a_loss_costs_k": f.adjusted_revenue_k})
    cuts = conc["cuts"]
    triggers = []
    if "region" in cuts:
        triggers.append({"cut": "region", "largest": cuts["region"]["largest"], "share": cuts["region"]["share"],
                         "fires": cuts["region"]["share"] > ROW_SHARE_OF_REGION_TRIGGER})
    if "end_customer" in cuts:
        triggers.append({"cut": "end_customer", "largest": cuts["end_customer"]["largest"],
                         "share": cuts["end_customer"]["share"],
                         "fires": cuts["end_customer"]["share"] > OEM_SHARE_OF_PORTFOLIO_TRIGGER})
    if "customer" in cuts:
        triggers.append({"cut": "customer", "largest": cuts["customer"]["largest"], "share": cuts["customer"]["share"],
                         "fires": cuts["customer"]["share"] > OEM_SHARE_OF_PORTFOLIO_TRIGGER})
    if "part_number" in cuts:
        triggers.append({"cut": "part_number", "largest": cuts["part_number"]["largest"],
                         "share": cuts["part_number"]["share"],
                         "fires": cuts["part_number"]["share"] > SUPPLY_RISK_PART_SHARE, "kind": "supply risk"})
    if "row" in cuts:
        triggers.append({"cut": "row", "largest": cuts["row"]["largest"], "share": cuts["row"]["share"],
                         "fires": cuts["row"]["share"] > ROW_SHARE_OF_REGION_TRIGGER})
    worst = max(triggers, key=lambda t: t["share"], default=None)
    return AnalysisResult(
        key="concentration_risk", label="Concentration risk",
        status="live" if ctx.financials else "partial",
        headline=(f"{worst['largest']} is {worst['share']:.0%} of the weighted pipeline ({worst['cut']})"
                  if worst else "no rows"),
        figures={"total_adjusted_revenue_k": conc["total_adjusted_revenue_k"], "triggers": triggers,
                 "cuts": {k: {"largest": v["largest"], "share": v["share"]} for k, v in cuts.items()}},
        rows=fired,
        note="Shares of C2. A row over 25% of its region or an OEM over 40% of the portfolio fires J-05 in the judgment layer.",
    )


ANALYSIS = Analysis(
    key="concentration_risk", label="Concentration risk",
    requires=frozenset({"V1", "V2", "V3", "V7", "V11", "V13", "V17"}), run=run,
    description="Single-row, customer, OEM, region and part dependency, with what a single loss would cost.",
)
