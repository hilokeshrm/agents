"""
Distributor POS/POR (WBS 11.4): the cheapest connector on the list and the one
that unblocks forecast accuracy. A scheduled CSV drop from Arrow, Avnet, WT
and similar -- part, customer, region, quarter, units, optionally resale
revenue -- becomes Actual rows (source "pos"), the cross-check to ERP revenue
(decision #69).
"""

import csv
import io

from sqlalchemy.orm import Session

from app.connectors._framework import ConnectorSpec, Observation
from app.db.models.actual import Actual
from app.db.models.field_value import TRUST_LEVELS
from app.intake.coerce import coerce_numeric
from app.registry.enums import canonicalize_customer, canonicalize_region


class POSConnector:
    spec = ConnectorSpec(
        name="disty_pos", label="Distributor POS / POR", trust=TRUST_LEVELS["pos"], cadence="monthly", source="pos",
        supplies=frozenset({"A2", "V13"}),
        description="Point-of-sale units per part, customer and quarter from the distributor's standard report.",
    )

    def load_actuals(self, db: Session, content: bytes, *, ref: str) -> int:
        written = 0
        for r in csv.DictReader(io.StringIO(content.decode("utf-8-sig"))):
            r = {k.strip().lower(): (v.strip() if isinstance(v, str) else v) for k, v in r.items()}
            db.add(Actual(
                part_number=r["part_number"], year=int(r["year"]), quarter=int(r["quarter"]), source="pos",
                region=canonicalize_region(r["region"]) if r.get("region") else None,
                customer=canonicalize_customer(r["customer"]) if r.get("customer") else None,
                units_kpcs=coerce_numeric(r.get("units_kpcs") or "").value,
                revenue_k=coerce_numeric(r.get("revenue_k") or "").value,
                invoiced_asp=coerce_numeric(r.get("resale_asp") or "").value, pull_ref=ref,
            ))
            written += 1
        db.flush()
        return written

    def pull(self, content: bytes, *, ref: str) -> list[Observation]:
        return []   # POS supplies actuals, not row fields
