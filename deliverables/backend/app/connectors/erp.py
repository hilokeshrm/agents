"""
ERP extract (WBS 11.5): bookings, backlog and invoiced revenue -- the primary
actual (decision #69). A nightly CSV extract with one row per part, customer
and quarter becomes Actual rows (source "erp") for forecast accuracy, plus an
invoiced-ASP observation against the matching opportunities at ERP trust,
which out-ranks a CRM or imported price but not a human edit.
"""

import csv
import io
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors._framework import ConnectorSpec, Observation
from app.db.models.actual import Actual
from app.db.models.field_value import TRUST_LEVELS
from app.db.models.opportunity import Opportunity
from app.intake.coerce import coerce_numeric
from app.registry.enums import canonicalize_customer, canonicalize_region

COLUMNS = {"part_number", "year", "quarter"}


def _rows(content: bytes) -> list[dict]:
    return [{k.strip().lower(): (v.strip() if isinstance(v, str) else v) for k, v in r.items()}
            for r in csv.DictReader(io.StringIO(content.decode("utf-8-sig")))]


class ERPConnector:
    spec = ConnectorSpec(
        name="erp", label="ERP extract", trust=TRUST_LEVELS["erp"], cadence="nightly", source="erp",
        supplies=frozenset({"A1", "A3", "V13"}),
        description="Shipped revenue, units and invoiced ASP per part, customer and quarter -- the primary actual.",
    )

    def parse(self, content: bytes) -> list[dict]:
        out = []
        for r in _rows(content):
            if not COLUMNS <= set(r):
                raise ValueError(f"ERP extract needs columns {sorted(COLUMNS)}; got {sorted(r)}")
            out.append({
                "part_number": r["part_number"], "year": int(r["year"]), "quarter": int(r["quarter"]),
                "region": canonicalize_region(r["region"]) if r.get("region") else None,
                "customer": canonicalize_customer(r["customer"]) if r.get("customer") else None,
                "revenue_k": coerce_numeric(r.get("revenue_k") or "").value,
                "units_kpcs": coerce_numeric(r.get("units_kpcs") or "").value,
                "invoiced_asp": coerce_numeric(r.get("invoiced_asp") or "").value,
            })
        return out

    def load_actuals(self, db: Session, content: bytes, *, ref: str) -> int:
        written = 0
        for r in self.parse(content):
            db.add(Actual(part_number=r["part_number"], region=r["region"], customer=r["customer"], year=r["year"],
                          quarter=r["quarter"], source="erp", units_kpcs=r["units_kpcs"], revenue_k=r["revenue_k"],
                          invoiced_asp=r["invoiced_asp"], pull_ref=ref))
            written += 1
        db.flush()
        return written

    def observations(self, db: Session, content: bytes, *, ref: str) -> list[Observation]:
        """Invoiced ASP as an observation against every open opportunity on
        that part, customer and region."""
        now = datetime.now(timezone.utc)
        out = []
        for r in self.parse(content):
            if r["invoiced_asp"] is None or not r["customer"] or not r["region"]:
                continue
            for opp in db.scalars(select(Opportunity).where(
                Opportunity.part_number == r["part_number"], Opportunity.customer == r["customer"],
                Opportunity.region == r["region"],
            )).all():
                out.append(Observation(field="disty_asp", value=r["invoiced_asp"], observed_at=now, ref=ref,
                                       external_id=opp.external_id))
        return out

    def pull(self, content: bytes, *, ref: str) -> list[Observation]:
        return []   # needs the session to find rows: see observations()
