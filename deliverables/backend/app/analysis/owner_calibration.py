"""Owner calibration (WBS 6.5, J-06): whose forecasts run optimistic, measured
against how their opportunities resolved. Reads the L5 calibration table the
quarterly batch writes (app/services/calibration.py); dark until resolved
outcomes exist (H3) and a rebuild has run (O1)."""

from sqlalchemy import select

from app.analysis.registry import Analysis, AnalysisContext, AnalysisResult


def run(ctx: AnalysisContext) -> AnalysisResult:
    from app.db.models.calibration import Calibration

    rows = []
    latest: dict[tuple, Calibration] = {}
    for c in ctx.db.scalars(select(Calibration).order_by(Calibration.computed_at)).all():
        latest[(c.owner, c.region)] = c
    for (owner, region), c in latest.items():
        rows.append({"owner": owner, "region": region, "bias_pp": c.bias_pp, "sd_pp": c.sd_pp,
                     "sample_size": c.sample_size, "reliable": c.reliable,
                     "window": f"{c.window_start.isoformat()}..{c.window_end.isoformat()}",
                     "reads": ("optimistic" if c.bias_pp > c.sd_pp else "conservative" if c.bias_pp < -c.sd_pp else "calibrated")})
    owners = [r for r in rows if r["owner"]]
    worst = max(owners, key=lambda r: abs(r["bias_pp"]), default=None)
    return AnalysisResult(
        key="owner_calibration", label="Owner calibration",
        status="live" if any(r["reliable"] for r in rows) else "partial",
        headline=(f"{worst['owner']} runs {worst['bias_pp']:+.0f}pp over {worst['sample_size']} resolved outcomes"
                  if worst else "no owner has enough resolved outcomes yet"),
        figures={"owners_measured": len(owners), "reliable": sum(1 for r in rows if r["reliable"])},
        rows=rows,
        note="Bias = mean(confidence before resolution - outcome) in pp; positive is optimistic. Reliable after two quarters (decision #70) and at least five outcomes.",
    )


ANALYSIS = Analysis(
    key="owner_calibration", label="Owner calibration",
    requires=frozenset({"H3", "O1", "V26"}), run=run,
    description="Whose confidence numbers historically ran optimistic or conservative, and by how much.",
)
