"""
NRE line splitter (WBS 3.5): FCST_Revenue rows with Design Status "NRE" are
non-recurring engineering charges -- one-off engineering work, design-tool
licences -- not silicon revenue, and must not be phased like it. Real examples
from the workbook: a one-off NRE charge recognised at $126K in one quarter, and
a recurring annual seven-seat licence at $210K appearing once per year
(docs/03-reference/Opportunity_Tracking_Agent_Tab_and_Field_Map.docx, section 4).

On an NRE row, Disty ASP is forced to 1 and the volume columns already hold
dollars directly, not units to multiply by a price. Reusing app/calc/engine.py's
Sales Revenue formula on an NRE row would still produce the right number today
(because ASP=1), but tags it as ProjectTrack-shaped silicon revenue -- exactly
what makes it phase wrong later, since WBS 5.5 (the quarterly phasing rule) has
no NRE case. This module gives NRE its own record type instead of letting it
hide inside ordinary volume revenue.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class VolumeRevenueRow:
    project: str
    part_number: str
    quarterly_revenue_k: dict  # {"CY25": [q1, q2, q3, q4], "CY26": [...], ...}
    total_revenue_k: float


@dataclass(frozen=True)
class NRECharge:
    project: str
    part_number: str
    quarterly_revenue_k: dict
    total_revenue_k: float


def _total(quarterly_revenue_by_year: dict) -> float:
    return sum(sum(quarters) for quarters in quarterly_revenue_by_year.values())


def split_nre_from_volume(fcst_rows: list) -> tuple[list, list]:
    """Splits FCST_Revenue rows by Design Status. A row is NRE (design_status ==
    "NRE", case-insensitive) or it is ordinary volume revenue -- there is no
    third case in the real file."""
    volume_rows: list[VolumeRevenueRow] = []
    nre_charges: list[NRECharge] = []

    for row in fcst_rows:
        quarterly = row["quarterly_revenue_k"]
        total = _total(quarterly)
        if row["design_status"].strip().upper() == "NRE":
            nre_charges.append(NRECharge(
                project=row["project"], part_number=row["part_number"],
                quarterly_revenue_k=quarterly, total_revenue_k=total,
            ))
        else:
            volume_rows.append(VolumeRevenueRow(
                project=row["project"], part_number=row["part_number"],
                quarterly_revenue_k=quarterly, total_revenue_k=total,
            ))
    return volume_rows, nre_charges


def reconciles_to_original(fcst_rows: list, volume_rows: list, nre_charges: list, tol: float = 0.01) -> bool:
    """WBS 3.5 done-when: volume revenue and NRE reconcile separately to the
    workbook, and their sum ties to the original column."""
    original_total = sum(_total(row["quarterly_revenue_k"]) for row in fcst_rows)
    split_total = sum(r.total_revenue_k for r in volume_rows) + sum(r.total_revenue_k for r in nre_charges)
    return abs(original_total - split_total) <= tol


def nre_by_quarter(fcst_rows) -> dict[tuple[int, int], float]:
    """C10 -- NRE recognised by quarter, from the workbook's own FCST_Revenue
    rows as the reader hands them over (`app/intake/xlsx_reader.RawRow`, fields
    `cy25_revenue_k_q1` .. `cy26_revenue_k_q4`). Only rows whose Design Status
    is NRE contribute; silicon rows are T2's business. On the real file this
    is $0 / $414K / $210K / $395K for CY25 -- $1,019K that has nothing to do
    with chip volume and was riding the volume columns with the price set to 1."""
    out: dict[tuple[int, int], float] = {}
    for row in fcst_rows:
        fields = row.fields if hasattr(row, "fields") else row
        if str(fields.get("design_status") or "").strip().upper() != "NRE":
            continue
        for name, value in fields.items():
            if "_revenue_k_q" not in name or value is None:
                continue
            try:
                year = 2000 + int(name[2:4])
                quarter = int(name[-1])
                amount = float(value)
            except (TypeError, ValueError):
                continue
            out[(year, quarter)] = out.get((year, quarter), 0.0) + amount
    return out
