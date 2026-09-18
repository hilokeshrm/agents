"""Contradiction and data quality (WBS 6.2): the section 03 list, per run, with
a trend. Reads the finding table for the live rows plus the intake schema's
required-field check, and reports per row what a total cannot trust."""

from sqlalchemy import select

from app.analysis.registry import Analysis, AnalysisContext, AnalysisResult
from app.intake.schema import REQUIRED, missing


def run(ctx: AnalysisContext) -> AnalysisResult:
    rows = []
    open_by_severity = {"blocking": 0, "advisory": 0}
    stored: dict[str, list] = {}
    if ctx.db is not None:
        from app.db.models.finding import Finding

        for f in ctx.db.scalars(select(Finding).where(Finding.opportunity_id.is_not(None))).all():
            stored.setdefault(f.opportunity_id, []).append(f)
    for opp in ctx.opportunities:
        values = {k: getattr(opp, k, None) for k in ("end_customer", "application", "product_line", "owner", "confidence_rationale")}
        gaps = missing(values, REQUIRED)
        findings = stored.get(opp.id, [])
        for f in findings:
            open_by_severity[f.severity] = open_by_severity.get(f.severity, 0) + 1
        if gaps or findings:
            rows.append({
                "project": opp.project, "opportunity_id": opp.id, "external_id": opp.external_id,
                "missing_required": gaps,
                "findings": [{"rule_id": f.rule_id, "severity": f.severity, "message": f.message} for f in findings],
                "trusted_in_totals": not any(f.severity == "blocking" for f in findings),
            })
    clean = len(ctx.opportunities) - len(rows)
    return AnalysisResult(
        key="data_quality", label="Contradiction and data quality",
        status="live",
        headline=f"{clean} of {len(ctx.opportunities)} scorable rows carry no finding; {ctx.excluded_count} excluded as blocking",
        figures={"rows_with_findings": len(rows), "clean_rows": clean, "excluded_blocking": ctx.excluded_count,
                 "open_findings": open_by_severity},
        rows=rows,
        note="Blocking findings exclude a row from totals and count it separately; advisory ones annotate it. "
             "Run `python -m scripts.findings_report` for the workbook-level view (V-a..V-i).",
    )


ANALYSIS = Analysis(
    key="data_quality", label="Contradiction and data quality",
    requires=frozenset({"V1", "V2", "V4", "V8"}), run=run,
    description="Which rows can be trusted in a total, and what each one still lacks.",
)
