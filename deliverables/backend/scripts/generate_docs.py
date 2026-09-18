"""
Generated documentation (WBS 15.3, 15.4): the rubric, Matrix A, the parameter
registry, the validation rules, the API and the MCP tool surface -- rendered
from the code that enforces them, so the page cannot drift from the rule.

    python -m scripts.generate_docs            # writes ../docs/generated/*.md
"""

import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[2] / "docs" / "generated"


def rubric_page() -> str:
    from app.judgment.matrix_b import EARLY_OPTIMISM_TOLERANCE, RULES, STAGE_ORDER
    from app.services.rubric_versions import LIFECYCLE_BANDS_V1, MATRIX_A_DEFAULTS, REVIEW_POLICY_V1, rubric_template

    caps = rubric_template()["caps"]
    lines = ["# Rubric -- Matrix A and Matrix B", "",
             "Generated from `app/judgment/matrix_b.py` and `app/services/rubric_versions.py`. "
             "The published rubric version in the database is the one in force; this page is the code's v1.", "",
             "## Matrix A -- valid pairings and baseline confidence (provisional, decision register section 2)", "",
             "| Design Status | " + " | ".join(STAGE_ORDER) + " |", "|---|" + "---|" * len(STAGE_ORDER)]
    statuses = ["Promotion", "Sample", "Evaluation", "Design In", "Design Win", "Mass Production"]
    for status in statuses:
        cells = [f"{MATRIX_A_DEFAULTS[(status, s)]:.2f}" if (status, s) in MATRIX_A_DEFAULTS else "forbidden" for s in STAGE_ORDER]
        lines.append(f"| {status} | " + " | ".join(cells) + " |")
    lines += ["| Lost | 0.00 (terminal, reachable from any stage; needs a loss reason) | | | |", "",
              f"Bounds: floor {caps['confidence_floor']}, ceiling {caps['confidence_ceiling']}, per-factor cap "
              f"{caps['factor_cap_pp']}pp, per-run cap {caps['run_cap_pp']}pp. Review policy: `{REVIEW_POLICY_V1}`.", "",
              "Lifecycle bands (a proposal crossing one always reaches a person): " +
              ", ".join(f"{b['label']} [{b['min'] if b['min'] is not None else '0'}, {b['max'] if b['max'] is not None else '1'})" for b in LIFECYCLE_BANDS_V1), "",
              f"Stage order: {' < '.join(STAGE_ORDER)}. Early = Concept or EVT. J-04 tolerance: {EARLY_OPTIMISM_TOLERANCE}.", "",
              "## Matrix B -- the thirteen factors", "",
              "| Rule | Key | Direction | Cap (pp) | Requires | Availability | Condition |", "|---|---|---|---|---|---|---|"]
    for r in RULES:
        lines.append(f"| {r.id} | `{r.key}` | {r.direction} | {r.cap_pp:g} | {', '.join(r.requires)} | {r.availability} | {r.guidance} |")
    lines += ["", "## Guards on the reply", "",
              "Every factor the model returns passes ten guards before it counts (`app/judgment/reply_guards.py`): "
              "schema, unknown rule, not assessable, missing citation (a verbatim quote from the bundle), "
              "Matrix A contradiction (J-01 on an allowed cell), not early (J-04 off Concept/EVT), wrong direction, "
              "out of range, no-op adjustment, over the factor cap (clipped and flagged). Then the "
              "`ConfidenceProposal` contract refuses to construct anything outside the bounds.", ""]
    return "\n".join(lines)


def parameters_page() -> str:
    from app.registry.parameters import PARAMS

    lines = ["# Parameter registry", "", "Generated from `app/registry/parameters.py`. Every rule, analysis and rubric factor "
             "cites a parameter by id, never a spreadsheet column name.", "",
             "| Id | Name | Type | Unit | Required | Tabs | Present | Note |", "|---|---|---|---|---|---|---|---|"]
    for p in PARAMS.all():
        lines.append(f"| {p.id} | {p.name} | {p.dtype.__name__} | {p.unit or ''} | {'yes' if p.required else ''} | "
                     f"{', '.join(p.tabs)} | {'yes' if p.present_in_current_file else 'proposed'} | {p.note} |")
    return "\n".join(lines) + "\n"


def rules_page() -> str:
    from app.guards.rules import RULES

    lines = ["# Validation rules V-a .. V-i", "", "Generated from `app/guards/rules.py`. Each rule is explainable in one sentence; "
             "`python -m scripts.findings_report` runs them over the workbook.", "",
             "| Rule | Label | Severity | Scope | Needs | In plain words |", "|---|---|---|---|---|---|"]
    for r in RULES:
        lines.append(f"| {r.id} | {r.label} | {r.severity} | {r.scope} | {', '.join(r.requires)} | {r.plain} |")
    return "\n".join(lines) + "\n"


def api_page() -> str:
    from app.main import app
    from app.mcp.server import tool_definitions

    spec = app.openapi()
    by_tag: dict[str, list[str]] = {}
    for path, methods in spec["paths"].items():
        for method, op in methods.items():
            tag = (op.get("tags") or ["other"])[0]
            summary = (op.get("summary") or op.get("description") or "").strip().split("\n")[0]
            by_tag.setdefault(tag, []).append(f"| `{method.upper()} {path}` | {summary} |")
    lines = ["# API and MCP reference", "", f"Generated from the running OpenAPI document (`/openapi.json`, version {spec['info']['version']}). "
             "Identity: a Bearer token from the configured OIDC issuer, a service account's `X-OppTrack-Api-Key`, or -- "
             "in development only -- the `X-OppTrack-Role` / `X-OppTrack-Regions` / `X-OppTrack-Actor` headers. Every "
             "response carries `X-Request-ID`.", ""]
    for tag in sorted(by_tag):
        lines += [f"## {tag}", "", "| Route | What it does |", "|---|---|", *sorted(by_tag[tag]), ""]
    lines += ["## MCP tools (read-only, `python -m app.mcp.server`)", "", "| Tool | Description |", "|---|---|"]
    for t in tool_definitions():
        lines.append(f"| `{t['name']}` | {t['description']} |")
    lines += ["", "Scope for the MCP server comes from `OPPTRACK_MCP_USER`, `OPPTRACK_MCP_ROLE` (default `finance`) and "
              "`OPPTRACK_MCP_REGIONS` (default `*`). There is no write tool.", ""]
    return "\n".join(lines)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    pages = {"rubric.md": rubric_page(), "parameters.md": parameters_page(), "validation-rules.md": rules_page(),
             "api-and-mcp-reference.md": api_page()}
    for name, content in pages.items():
        (OUT / name).write_text(content, encoding="utf-8")
        print(f"wrote {OUT / name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
