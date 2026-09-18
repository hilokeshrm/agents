"""
One-time crosswalk backfill (WBS 2.4, 9.8, decision #57).

Rows created before the sequential id existed carry a random OPP-<hex> id.
This mints the next OPP-000001-style id for each, in creation order, writes
the old id as provenance (so the crosswalk is on record, never lost), and
prints old -> new. Idempotent: a row already carrying a sequential id is left
alone. Uncertain duplicates are never merged (decision #57): the script only
renames, it never joins two rows.

    python -m scripts.backfill_ids            # apply
    python -m scripts.backfill_ids --dry-run  # print the crosswalk only
"""

import re
import sys
from datetime import datetime, timezone

from sqlalchemy import select

from app.db.models.field_value import TRUST_LEVELS
from app.db.models.field_value import FieldValue as FieldValueRow
from app.db.models.opportunity import Opportunity, next_external_id
from app.db.session import SessionLocal

SEQUENTIAL = re.compile(r"^OPP-\d{6}$")


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    db = SessionLocal()
    try:
        rows = db.scalars(select(Opportunity).order_by(Opportunity.created_at)).all()
        crosswalk = []
        for opp in rows:
            if SEQUENTIAL.match(opp.external_id or ""):
                continue
            old = opp.external_id
            new = next_external_id(db) if not dry else "OPP-??????"
            crosswalk.append((opp.project, old, new))
            if dry:
                continue
            opp.external_id = new
            db.add(FieldValueRow(opportunity_id=opp.id, param="V28", value=f"{new} (was {old})", source="import",
                                 trust=TRUST_LEVELS["import"], captured_at=datetime.now(timezone.utc)))
        if dry:
            db.rollback()
        else:
            db.commit()
        for project, old, new in crosswalk:
            print(f"{project:14} {old:20} -> {new}")
        print(f"{len(crosswalk)} row(s) {'would be' if dry else ''} renumbered; {len(rows) - len(crosswalk)} already sequential")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
