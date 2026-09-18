"""
CRM sync (WBS 11.3): dimensions, identity and status from a CRM export.

Reads the CRM's opportunity export (CSV or JSON list) using the same header
aliases the import wizard understands, plus the CRM's own record id as the
external id crosswalk. Supplies the D-dimensions and the design status; the
status is a gated field, so a CRM stage that disagrees with the row is a
reconciliation item, never a write (decision #63: CRM sits below a human edit
and below ERP).
"""

import csv
import io
import json
from datetime import datetime, timezone

from app.connectors._framework import ConnectorSpec, Observation
from app.db.models.field_value import TRUST_LEVELS
from app.intake.coerce import coerce_date, coerce_numeric
from app.registry.enums import canonicalize_customer, canonicalize_design_status, canonicalize_region, canonicalize_stage
from app.services.imports import HEADER_ALIASES

FIELDS = ("end_customer", "application", "product_line", "design_status", "stage", "mp_date",
          "eau_kpcs", "competitor_part", "owner")


class CRMConnector:
    spec = ConnectorSpec(
        name="crm", label="CRM sync", trust=TRUST_LEVELS["crm"], cadence="nightly", source="crm",
        supplies=frozenset({"V1", "V2", "V3", "V4", "V5", "V6", "V7", "V8", "V10", "V11", "V16", "V26", "V28"}),
        description="Dimensions, identity and declared status from the CRM's opportunity export.",
    )

    def pull(self, content: bytes, *, ref: str) -> list[Observation]:
        text = content.decode("utf-8-sig")
        records = json.loads(text) if text.lstrip().startswith("[") else list(csv.DictReader(io.StringIO(text)))
        now = datetime.now(timezone.utc)
        out: list[Observation] = []
        for rec in records:
            row = {HEADER_ALIASES.get(str(k).strip().lower(), str(k).strip().lower()): v for k, v in rec.items()}
            region = canonicalize_region(str(row.get("region") or "")) if row.get("region") else None
            customer = canonicalize_customer(str(row.get("customer") or "")) if row.get("customer") else None
            identity = (region, customer, row.get("project"), row.get("part_number")) if all(
                (region, customer, row.get("project"), row.get("part_number"))) else None
            external_id = (str(row.get("external_id") or "")).strip() or None
            for f in FIELDS:
                raw = row.get(f)
                if raw in (None, ""):
                    continue
                value: object = raw
                if f == "design_status":
                    value = canonicalize_design_status(str(raw))
                elif f == "stage":
                    value = canonicalize_stage(str(raw))
                elif f == "mp_date":
                    value = coerce_date(str(raw)).value
                elif f == "eau_kpcs":
                    value = coerce_numeric(str(raw)).value
                if value is None:
                    continue
                out.append(Observation(field=f, value=value, observed_at=now, ref=ref,
                                       external_id=external_id, identity=identity))
        return out
