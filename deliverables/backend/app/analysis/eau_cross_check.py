"""EAU cross-check and white-space detection (WBS 11.6, Phase 5): validates a
row's implied vehicle sets against the licensed programme build volume, and
lists programmes in the design-in horizon with no opportunity registered.
Dark until the market_programme table has rows (P1/P2)."""

from datetime import timedelta

from sqlalchemy import select

from app.analysis.registry import Analysis, AnalysisContext, AnalysisResult

HORIZON_DAYS = 3 * 365          # a socket is won two to three years before SoP
IMPLAUSIBLE_RATIO = 1.5         # sets implied by EAU vs the programme's build


def run(ctx: AnalysisContext) -> AnalysisResult:
    from app.db.models.market_programme import MarketProgramme

    programmes = ctx.db.scalars(select(MarketProgramme)).all()
    by_oem: dict[str, list[MarketProgramme]] = {}
    for p in programmes:
        by_oem.setdefault(p.oem.strip().lower(), []).append(p)

    checks = []
    for f, opp in zip(ctx.financials, ctx.opportunities):
        if f.set_volume is None:
            continue
        candidates = by_oem.get((opp.end_customer or "").strip().lower(), [])
        if opp.application:
            narrowed = [p for p in candidates if (p.application or "").strip().lower() == opp.application.strip().lower()]
            candidates = narrowed or candidates
        build = sum(p.build_volume_ksets or 0.0 for p in candidates)
        if build <= 0:
            continue
        ratio = f.set_volume / build
        checks.append({"project": f.project, "opportunity_id": opp.id, "implied_ksets": f.set_volume,
                       "programme_build_ksets": build, "ratio": ratio, "implausible": ratio > IMPLAUSIBLE_RATIO,
                       "programmes": [p.programme for p in candidates]})

    covered = {((o.end_customer or "").strip().lower(), (o.application or "").strip().lower()) for o in ctx.opportunities}
    white_space = []
    horizon_end = ctx.as_of + timedelta(days=HORIZON_DAYS)
    for p in programmes:
        if p.sop is None or not (ctx.as_of <= p.sop <= horizon_end):
            continue
        key = (p.oem.strip().lower(), (p.application or "").strip().lower())
        if key not in covered and (p.oem.strip().lower(), "") not in covered:
            white_space.append({"programme": p.programme, "oem": p.oem, "application": p.application,
                                "sop": p.sop.isoformat(), "build_volume_ksets": p.build_volume_ksets})
    flagged = [c for c in checks if c["implausible"]]
    return AnalysisResult(
        key="eau_cross_check", label="EAU cross-check and white space", status="live",
        headline=f"{len(flagged)} row(s) exceed their programme's build; {len(white_space)} programme(s) in the horizon with no opportunity",
        figures={"rows_checked": len(checks), "implausible": [c["project"] for c in flagged], "white_space": len(white_space)},
        rows=checks + [{"kind": "white_space", **w} for w in white_space],
        note="A socket's implied vehicle sets (EAU / Unit-per-set) against the licensed programme build; white space is an OEM programme with SoP inside three years and nothing registered.",
    )


ANALYSIS = Analysis(
    key="eau_cross_check", label="EAU cross-check and white space",
    requires=frozenset({"P1", "P2", "V3", "V11", "V12"}), run=run,
    description="Validates EAU against real platform build forecasts; lists programmes in the horizon with no opportunity.",
)
