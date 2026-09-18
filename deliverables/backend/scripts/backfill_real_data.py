"""
One-time backfill (WBS 9.8, built ahead of its formal dependency on 2.4): loads
ProjectTrack's nine complete rows from the real TrackF (1).xlsx directly into the
live database, through the same canonicalize -> provenance pipeline the API
uses (source="import", the lowest trust tier -- see app/db/models/field_value.py
-- so a later human edit or connector value supersedes it without a conflict).

Deliberately does not touch Funnel's eight rows: the source document is explicit
that Funnel carries "no Stage, no Confidence" at all
(docs/03-reference/Opportunity_Tracking_Agent_Tab_and_Field_Map.docx, section 3),
and both are NOT NULL on Opportunity. Backfilling them would mean inventing a
stage or a confidence figure the workbook never recorded -- exactly what every
other module in this codebase refuses to do. Funnel rows wait for the workbook
reader (WBS 3.1) and a decision on how to represent a stage-less, confidence-less
record, not for this script to guess one.

owner="Unassigned" and confidence_rationale state their own absence rather than
inventing plausible-sounding content -- ProjectTrack has no Owner column and no
per-row confidence rationale; that omission is the field-map document's own
finding, not something this script papers over.

Run: python -m scripts.backfill_real_data (from backend/, with DATABASE_URL set
the same way the app itself is run).
"""

import sys
from pathlib import Path

WORKBOOK = Path(__file__).resolve().parents[3] / "data" / "TrackF (1).xlsx"

OWNER = "Unassigned"
CONFIDENCE_RATIONALE = (
    "Imported from TrackF (1).xlsx, ProjectTrack tab -- no per-row rationale was "
    "recorded in the source; Confidence Level is the sheet's own value, carried as-is."
)


def main() -> None:
    import openpyxl

    from app.db.models.field_value import TRUST_LEVELS
    from app.db.models.field_value import FieldValue as FieldValueRow
    from app.db.models.opportunity import Opportunity
    from app.db.session import SessionLocal
    from app.intake.canonicalize import canonicalize_row
    from app.intake.coerce import coerce_date
    from app.intake.provenance import wrap_row
    from app.services.state_transitions import seed_initial_state

    if not WORKBOOK.exists():
        print(f"Workbook not found at {WORKBOOK}; nothing to backfill.", file=sys.stderr)
        sys.exit(1)

    wb = openpyxl.load_workbook(WORKBOOK, data_only=True)
    ws = wb["ProjectTrack"]

    db = SessionLocal()
    created, skipped = 0, 0
    try:
        existing_projects = {o.project for o in db.query(Opportunity).all()}

        for r in range(5, 14):  # rows 5-13: the nine complete ProjectTrack rows
            (region, customer, end_customer, project, application, product_line, part_number,
             design_status, stage, mp_raw, eau, unit_set, disty_asp, resale_asp, _sales_rev,
             competitor_part, confidence) = (ws.cell(row=r, column=c).value for c in range(1, 18))

            if project in existing_projects:
                skipped += 1
                continue

            mp_date = coerce_date(mp_raw).value if mp_raw else None

            raw_row = {
                "region": region, "customer": customer, "end_customer": end_customer,
                "project": project, "application": application, "product_line": product_line,
                "part_number": part_number, "design_status": design_status, "stage": stage,
                "mp_date": mp_date, "eau_kpcs": eau, "unit_set": unit_set,
                "disty_asp": disty_asp, "resale_asp": resale_asp, "confidence": confidence,
                "competitor_part": competitor_part, "owner": OWNER, "evidence": None,
                "confidence_rationale": CONFIDENCE_RATIONALE,
            }

            result = canonicalize_row(raw_row)
            if result.findings:
                print(f"  SKIPPED {project!r}: {[f.message for f in result.findings]}", file=sys.stderr)
                continue

            opp = Opportunity(**result.canonical)
            db.add(opp)
            db.flush()

            for fv in wrap_row(result.canonical, source="import", trust=TRUST_LEVELS["import"]).values():
                db.add(FieldValueRow(
                    opportunity_id=opp.id, param=fv.param, value=str(fv.value),
                    source=fv.source, trust=fv.trust, captured_at=fv.at,
                ))

            seed_initial_state(db, opp, actor="backfill:ProjectTrack")
            created += 1
            print(f"  created {project!r} ({region}, {design_status}, ${opp.eau_kpcs * opp.disty_asp:,.0f}K sales)")

        db.commit()
    finally:
        db.close()

    print(f"\nBackfill complete: {created} created, {skipped} already present.")


if __name__ == "__main__":
    main()
