"""
Vehicle programme data (WBS 11.6): a licensed feed (S&P Global Mobility,
MarkLines, LMC class) of platforms, OEMs, SoP dates and build volumes. Two
uses: the real check behind J-11 (EAU against the programme's actual build)
and white-space detection -- programmes in the design-in horizon with no
opportunity registered against them.

The licence is the only recurring external cost in the plan and is not in
hand; this connector reads the feed's CSV shape so the day it is, nothing
else changes. Until then the market_programme table is empty and the EAU
cross-check and white-space analyses report dark, naming P1/P2.
"""

import csv
import io

from sqlalchemy.orm import Session

from app.connectors._framework import ConnectorSpec, Observation
from app.db.models.field_value import TRUST_LEVELS
from app.db.models.market_programme import MarketProgramme
from app.intake.coerce import coerce_date, coerce_numeric
from app.registry.enums import canonicalize_region


class MarketDataConnector:
    spec = ConnectorSpec(
        name="market_data", label="Vehicle programme data", trust=TRUST_LEVELS["market"], cadence="monthly",
        source="market",
        supplies=frozenset({"P1", "P2"}),
        description="Licensed platform build forecasts and SoP dates; feeds the EAU cross-check and white-space detection.",
    )

    def load(self, db: Session, content: bytes, *, ref: str) -> int:
        written = 0
        for r in csv.DictReader(io.StringIO(content.decode("utf-8-sig"))):
            r = {k.strip().lower(): (v.strip() if isinstance(v, str) else v) for k, v in r.items()}
            db.add(MarketProgramme(
                programme=r["programme"], oem=r["oem"],
                region=canonicalize_region(r["region"]) if r.get("region") else None,
                application=r.get("application"), sop=coerce_date(r.get("sop") or "").value,
                build_volume_ksets=coerce_numeric(r.get("build_volume_ksets") or "").value, pull_ref=ref,
            ))
            written += 1
        db.flush()
        return written

    def pull(self, content: bytes, *, ref: str) -> list[Observation]:
        return []
