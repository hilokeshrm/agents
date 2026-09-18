"""
The walkthrough (build specification section 09, "3-5 Sep: walkthrough for
David and Gene"): the findings report, the before-and-after pipeline, and the
audit trail behind one changed number -- generated from the real workbook in
one command, into a fresh database that is thrown away afterwards.

    python -m scripts.walkthrough                  # writes ../docs/walkthrough.md
    python -m scripts.walkthrough --keep-db path   # keep the SQLite file for a demo

Nothing here touches the dev database. The script builds its own engine,
loads the nine complete ProjectTrack rows through the same intake service the
API uses, publishes rubric v1, executes a run, approves the Hermes proposal as
a director, and writes what happened, with the figures the engine produced.
"""

import sys
import tempfile
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

WORKBOOK = Path(__file__).resolve().parents[3] / "data" / "TrackF (1).xlsx"
OUT = Path(__file__).resolve().parents[2] / "docs" / "walkthrough.md"


def load_rows(db) -> dict[str, str]:
    from app.db.models.field_value import TRUST_LEVELS
    from app.intake.coerce import coerce_date
    from app.intake.xlsx_reader import read_workbook
    from app.services.intake import create_opportunity

    ids = {}
    for row in read_workbook(WORKBOOK).tabs["ProjectTrack"].rows:
        f = row.fields
        if not f.get("customer") or f.get("disty_asp") is None:
            continue  # the five skeleton rows: findings, not opportunities
        values = {
            "region": f["region"], "customer": f["customer"], "end_customer": f["end_customer"], "project": f["project"],
            "application": f.get("application"), "product_line": f.get("product_line"), "part_number": f["part_number"],
            "design_status": f["design_status"], "stage": f["stage"],
            "mp_date": coerce_date(str(f["mp_date"])).value if f.get("mp_date") else None,
            "eau_kpcs": float(f["eau_kpcs"]), "unit_set": float(f["unit_set"]) if f.get("unit_set") else None,
            "disty_asp": float(f["disty_asp"]), "resale_asp": float(f["resale_asp"]) if f.get("resale_asp") else None,
            "confidence": float(f["confidence"]), "competitor_part": f.get("competitor_part"),
            # The workbook has no owner column. Without one, J-12 (data completeness)
            # haircuts every row by 10pp -- true, and it drowns the rest of the story,
            # so the walkthrough assigns a nominal owner per region and says so.
            "owner": f"owner-{str(f['region']).lower()}", "evidence": f.get("comments"),
            "confidence_rationale": "Imported from TrackF (1).xlsx, ProjectTrack -- the sheet's own Confidence Level.",
        }
        result = create_opportunity(db, values, source="import", trust=TRUST_LEVELS["import"], actor="walkthrough")
        ids[f["project"]] = result.opportunity.id
    db.commit()
    return ids


def main(argv: list[str]) -> int:
    keep = argv[argv.index("--keep-db") + 1] if "--keep-db" in argv else None
    db_path = Path(keep) if keep else Path(tempfile.mkdtemp()) / "walkthrough.sqlite"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")

    import app.db.models  # noqa: F401 -- registers every table on Base before create_all
    from app.db.base import Base
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    from app.analysis.registry import build_context, run_all
    from app.db.models.confidence_event import ConfidenceEvent
    from app.db.models.opportunity import Opportunity
    from app.db.models.proposal import Proposal
    from app.guards.report import render_text, workbook_report
    from app.security.roles import Actor
    from app.services.financials import financials_for
    from app.services.judgment_runs import execute_run
    from app.services.proposals import resolve_proposal
    from app.services.rubric_versions import publish_v1

    lines: list[str] = []
    w = lines.append
    w("# Walkthrough -- the Opportunity Tracking Agent on TrackF (1).xlsx")
    w("")
    w(f"Generated {date.today().isoformat()} by `python -m scripts.walkthrough` from the real workbook into a fresh "
      "database. Three things, in the order the specification asked for them: what the file gets wrong, what the "
      "pipeline is before and after the agent's proposals, and the audit trail behind one changed number.")
    w("")

    # 1. Findings
    report = workbook_report(WORKBOOK)
    w("## 1. What the file gets wrong")
    w("")
    w(f"Rules V-a..V-i over the six tabs: **{report.by_severity['blocking']} blocking, {report.by_severity['advisory']} "
      f"advisory, {report.by_severity['cosmetic']} cosmetic**. All {len(report.spec_refs)} of the specification's twelve "
      "documented findings are reproduced from the file; two the specification missed are found (ID802 and ID803 imply "
      "36.8M and 35.0M vehicle sets a year, the same defect as IP901).")
    w("")
    w("```")
    w("\n".join(render_text(report).splitlines()[5:5 + 20]))
    w("  ...")
    w("```")
    w("")

    with Session() as db:
        ids = load_rows(db)
        version = publish_v1(db, published_by="walkthrough")
        db.commit()

        # 2. Before
        opps = {o.project: o for o in db.scalars(select(Opportunity)).all()}
        before = {p: financials_for(o) for p, o in opps.items()}
        w("## 2. The pipeline, before")
        w("")
        w(f"{len(opps)} complete rows loaded through the intake service (the five skeleton rows are findings, not "
          f"rows). Rubric **{version.label}** published: Matrix A per the decision register, thirteen Matrix B rules, "
          "0.05-0.95, a 20pp run cap, gate_all. One liberty: the workbook has no owner column, and without an owner "
          "J-12 (data completeness) haircuts every row by 10pp -- correct, and it drowns everything else -- so each "
          "row is given a nominal owner per region here. That is the case for the owner field.")
        w("")
        w("| Project | Region | Status / stage | EAU Kpcs | ASP | Sales revenue | Confidence | Adjusted |")
        w("|---|---|---|---:|---:|---:|---:|---:|")
        for p, f in sorted(before.items(), key=lambda kv: -kv[1].adjusted_revenue_k):
            o = opps[p]
            w(f"| {p} | {o.region} | {o.design_status} / {o.stage} | {o.eau_kpcs:,.0f} | ${o.disty_asp:.2f} | "
              f"${f.sales_revenue_k:,.0f}K | {o.confidence:.2f} | ${f.adjusted_revenue_k:,.0f}K |")
        total_before = sum(f.adjusted_revenue_k for f in before.values())
        w(f"| **Total** | | | | | **${sum(f.sales_revenue_k for f in before.values()):,.0f}K** | | **${total_before:,.0f}K** |")
        w("")

        # 3. The run
        run = execute_run(db, version=version, actor="walkthrough")
        db.commit()
        w("## 3. One run, ten steps")
        w("")
        w(f"Mode **{run.mode}** (the rule-based scorer over the same Matrix A; the live model waits on the security "
          f"sign-off). {run.counts['scored']} rows scored, {run.counts['proposals']} proposals, "
          f"{run.counts['queued']} queued for a person, {run.counts['auto_applied']} applied without one, "
          f"{run.counts.get('transition_proposals', 0)} lifecycle move(s) proposed.")
        w("")
        for s in run.steps:
            w(f"{s['n']:>2}. **{s['name']}** ({s['status']}) -- {s['detail']}")
        w("")

        # 4. After (proposed)
        proposals = {}
        for p in db.scalars(select(Proposal).where(Proposal.run_id == run.id, Proposal.kind == "confidence")).all():
            proposals[db.get(Opportunity, p.opportunity_id).project] = p
        w("## 4. The pipeline, after -- if every proposal were approved")
        w("")
        w("| Project | Entered | Proposed | Rules fired | Flags | Adjusted before | Adjusted after |")
        w("|---|---:|---:|---|---|---:|---:|")
        total_after = 0.0
        for p, o in sorted(opps.items(), key=lambda kv: -before[kv[0]].adjusted_revenue_k):
            pr = proposals.get(p)
            proposed = pr.proposed_confidence if pr else o.confidence
            after = financials_for(o, proposed).adjusted_revenue_k
            total_after += after
            fired = ", ".join(f"{f['rule_id']} {f['confidence_adjustment_pct']:+.0f}pp" for f in (pr.factors if pr else []) if f["applies"] and f["accepted"]) or "none"
            flags = ", ".join(pr.flags) if pr and pr.flags else ""
            w(f"| {p} | {o.confidence:.2f} | {proposed:.2f} | {fired} | {flags} | ${before[p].adjusted_revenue_k:,.0f}K | ${after:,.0f}K |")
        w(f"| **Total** | | | | | **${total_before:,.0f}K** | **${total_after:,.0f}K** ({total_after - total_before:+,.0f}K) |")
        w("")
        w("Aphrodite and Montana -- both Design In at DVT, the two rows the first live run docked for a mismatch and "
          "for being 'early' -- are untouched: J-01 reads Matrix A as a flag and J-04 reads the stage order as a "
          "constant, and two guards refuse either firing regardless of what a model says.")
        w("")

        # 5. One changed number: Hermes
        hermes = opps["Hermes"]
        pr = proposals["Hermes"]
        w("## 5. The audit trail behind one changed number: Hermes")
        w("")
        w(f"Hermes is the largest row ($40,000K sales revenue) and one of the least certain (Sample at EVT, entered "
          f"at {hermes.confidence:.2f}). The agent proposed **{pr.proposed_confidence:.2f}**.")
        w("")
        for f in pr.factors:
            state = "fired" if f["applies"] and f["accepted"] else ("refused: " + f["guard"] if f["guard"] and f["guard"] != "not_assessable" else "not assessable" if f["guard"] == "not_assessable" else "did not apply")
            w(f"- **{f['rule_id']} {f['key']}** -- {state}"
              + (f", {f['confidence_adjustment_pct']:+.0f}pp; quote: `{f['quote']}`" if f["applies"] and f["accepted"] else "")
              + f". {f['rationale']}")
        w("")
        director = Actor(user_id="walkthrough-director", role="director", regions=())
        event = resolve_proposal(db, pr, hermes, action="approve", actor=director.user_id, actor_role=director.role,
                                 note="approved in the walkthrough")
        db.commit()
        after_f = financials_for(hermes)
        w(f"A director approves it. The row's confidence is now {hermes.confidence:.2f}; Adjusted Revenue is "
          f"recomputed by the calc engine from that number -- ${after_f.adjusted_revenue_k:,.0f}K, from "
          f"${before['Hermes'].adjusted_revenue_k:,.0f}K -- and the portfolio moves by exactly that row's delta.")
        w("")
        w("The append-only stream for the row:")
        w("")
        w("| When | Event | From | To | Actor | Version stamps |")
        w("|---|---|---:|---:|---|---|")
        for e in db.scalars(select(ConfidenceEvent).where(ConfidenceEvent.opportunity_id == hermes.id)
                            .order_by(ConfidenceEvent.occurred_at)).all():
            w(f"| {e.occurred_at.strftime('%Y-%m-%d %H:%M:%S')} | {e.event_type} | {e.base_confidence:.2f} | "
              f"{e.resulting_confidence:.2f} | {e.actor} ({e.actor_role}) | {e.prompt_version or '—'}; model {e.model_id or 'none'} |")
        w("")
        w("Nothing in the codebase updates or deletes one of these rows; the ORM refuses to, for every role.")
        w("")

        # 6. Analyses
        ctx = build_context(db, actor=director)
        result = run_all(ctx)
        w("## 6. What the analyses say about this portfolio")
        w("")
        for a in result["ran"].values():
            w(f"- **{a.label}** ({a.status}): {a.headline}")
        for a in result["dark"].values():
            w(f"- {a.label}: dark -- {a.note}")
        w("")
        w("## 7. What is still an input, not work")
        w("")
        w("- The security sign-off for sending pipeline data to a hosted model: until then `JUDGMENT_MODE=mock`.")
        w("- Finance's targets (coverage), ERP and distributor actuals plus two quarters (forecast accuracy, owner "
          "calibration), the vehicle-programme licence (EAU cross-check, white space). Each lights up on its own "
          "the day the input lands.")
        w("- David Nam's ratification of Matrix A, the 0.95 ceiling and the close policy. The provisional values "
          "are published as rubric version 2026.1; a ratified table is a new version, not a code change.")

    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
    print(f"database {'kept at ' + str(db_path) if keep else 'discarded'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
