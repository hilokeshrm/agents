"""
Deterministic pipeline calculation engine (Work Breakdown package 5.0, C1/C2/T2
done; C3-C7 below).

Ported from opptrack_poc/calc_engine.py, the validated POC contract: this reimplements
exactly the arithmetic in TrackF_1.xlsx (Funnel, ProjectTrack, Mass Production, Design
Lost tabs) as plain, testable Python, with zero LLM involvement.

Sales Revenue    = EAU (Kpcs) x Distributor ASP        (ProjectTrack: O = K * M)
Adjusted Revenue = Sales Revenue x Confidence Level     (ProjectTrack: R = O * Q)

The judgment layer (app/judgment/rubric.py) only ever proposes a *replacement or
adjustment* to the human-entered Confidence Level, never touches this math. The base
case and the calibrated case must be the same function called twice (see
docs/02-architecture/OppTrack_Work_Breakdown.html, package 5.0) -- that is the only
reason the delta between them means anything.

C3-C7 (docs/03-reference/Opportunity_Tracking_Agent_Tab_and_Field_Map.docx, the
ProjectTrack column dictionary): none of these exist in the workbook -- they are
figures the sheet collects the inputs for and never computes.
  C3 Set volume        = EAU / Unit-Set              ("Set volume = EAU divided by Unit/Set")
  C4 Attach rate        = EAU / Set volume             reconciles to Unit-Set by construction
                                                        (see test_set_volume_and_attach_rate_reconcile)
  C5 Channel margin $   = Resale ASP - Disty ASP       ("Resale minus Disty, is free analysis
  C6 Channel margin %   = (Resale ASP - Disty ASP)      sitting in data already collected")
                          / Resale ASP
  C7 Part-level demand  = part_level_demand(), below
  NRE                   = nre_charge_k, carried beside volume revenue and never
                          summed into it (WBS 3.5; app/calc/nre.py splits the
                          workbook's own NRE rows on the same principle)    ("Aggregates unit demand across every
                                                        socket using the same part")

Unit-Set and Resale ASP are both optional inputs (WBS 2.1 V12, V14 -- not every row
carries them, and Unit-Set in particular was "dropped entirely from the POC's sample
data"). Missing either one means the figures it feeds are None, never a guessed value
standing in for a real one -- the same not-invented discipline app/intake/canonicalize.py
applies to enum fields.

Remaining scope (C10-C12): NRE recognition by quarter and the quarterly phasing rule.
"""

from dataclasses import dataclass


@dataclass
class ProjectFinancials:
    project: str
    region: str
    customer: str
    end_customer: str | None
    product_line: str | None
    stage: str
    design_status: str
    part_number: str
    eau_kpcs: float
    sales_revenue_k: float
    confidence: float
    adjusted_revenue_k: float
    # Non-recurring engineering, kept beside silicon volume revenue and never
    # inside it (WBS 3.5). An NRE charge is one-off engineering work, not units
    # times a price, so folding it into Sales Revenue would make it phase like
    # silicon in every downstream quarter. Both the entered charge and the
    # confidence-weighted view are reported, because which of the two belongs in
    # a forecast is a policy question nobody has ratified -- see the forecast
    # feed's note in app/api/v1/scenarios.py.
    nre_revenue_k: float
    nre_weighted_k: float
    set_volume: float | None  # C3
    attach_rate: float | None  # C4
    channel_margin_usd: float | None  # C5
    channel_margin_pct: float | None  # C6


def compute_project_financials(row: dict) -> ProjectFinancials:
    """Row-level calc matching ProjectTrack columns O and R exactly, plus C3-C7."""
    sales_revenue = row["eau_kpcs"] * row["disty_asp"]
    adjusted_revenue = sales_revenue * row["confidence"]

    # None and 0.0 are the same figure here, but they are not the same fact: a
    # row with no NRE contributes nothing either way, so both collapse to 0.0
    # rather than propagating a null through every total.
    nre_revenue = float(row.get("nre_charge_k") or 0.0)

    unit_set = row.get("unit_set")
    set_volume = (row["eau_kpcs"] / unit_set) if unit_set else None
    attach_rate = (row["eau_kpcs"] / set_volume) if set_volume else None

    resale_asp = row.get("resale_asp")
    if resale_asp:
        channel_margin_usd = resale_asp - row["disty_asp"]
        channel_margin_pct = channel_margin_usd / resale_asp
    else:
        channel_margin_usd = None
        channel_margin_pct = None

    return ProjectFinancials(
        project=row["project"],
        region=row["region"],
        customer=row["customer"],
        end_customer=row.get("end_customer"),
        product_line=row.get("product_line"),
        stage=row.get("stage", row.get("design_status", "")),
        design_status=row["design_status"],
        part_number=row["part_number"],
        eau_kpcs=row["eau_kpcs"],
        sales_revenue_k=sales_revenue,
        confidence=row["confidence"],
        adjusted_revenue_k=adjusted_revenue,
        nre_revenue_k=nre_revenue,
        nre_weighted_k=nre_revenue * row["confidence"],
        set_volume=set_volume,
        attach_rate=attach_rate,
        channel_margin_usd=channel_margin_usd,
        channel_margin_pct=channel_margin_pct,
    )


def compute_pipeline(project_track_rows: list) -> list:
    return [compute_project_financials(r) for r in project_track_rows]


def part_level_demand(financials: list) -> dict:
    """C7: aggregates unit demand across every socket using the same part number
    -- the input capacity planning needs. A part on six rows shows up as one
    entry with six projects and their summed EAU, not six numbers a person has
    to add up by hand."""
    demand: dict = {}
    for f in financials:
        entry = demand.setdefault(f.part_number, {"eau_kpcs": 0.0, "projects": []})
        entry["eau_kpcs"] += f.eau_kpcs
        entry["projects"].append(f.project)
    return demand


def portfolio_rollup(financials: list) -> dict:
    """Aggregate deterministic pipeline revenue across the supported dimensions.

    Concentration is returned as a descending ranking of adjusted revenue share;
    it is descriptive output, not a judgment adjustment by itself.
    """
    by_region = {}
    by_stage = {}
    by_customer = {}
    by_end_customer = {}
    by_product_line = {}
    by_part_number = {}
    by_design_status = {}
    total_sales = 0.0
    total_adjusted = 0.0
    total_nre = 0.0
    total_nre_weighted = 0.0

    for f in financials:
        by_region.setdefault(f.region, {"sales_revenue_k": 0.0, "adjusted_revenue_k": 0.0, "nre_revenue_k": 0.0})
        by_region[f.region]["sales_revenue_k"] += f.sales_revenue_k
        by_region[f.region]["adjusted_revenue_k"] += f.adjusted_revenue_k
        by_region[f.region]["nre_revenue_k"] += f.nre_revenue_k

        by_stage.setdefault(f.stage, {"sales_revenue_k": 0.0, "adjusted_revenue_k": 0.0, "nre_revenue_k": 0.0, "count": 0})
        by_stage[f.stage]["sales_revenue_k"] += f.sales_revenue_k
        by_stage[f.stage]["adjusted_revenue_k"] += f.adjusted_revenue_k
        by_stage[f.stage]["nre_revenue_k"] += f.nre_revenue_k
        by_stage[f.stage]["count"] += 1

        _add_group(by_customer, f.customer, f)
        _add_group(by_end_customer, getattr(f, "end_customer", "") or "Unspecified", f)
        _add_group(by_product_line, getattr(f, "product_line", "") or "Unspecified", f)
        _add_group(by_part_number, f.part_number, f)
        _add_group(by_design_status, f.design_status, f)

        total_sales += f.sales_revenue_k
        total_adjusted += f.adjusted_revenue_k
        total_nre += f.nre_revenue_k
        total_nre_weighted += f.nre_weighted_k

    concentration = sorted(
        (
            {"group": group, "adjusted_revenue_k": values["adjusted_revenue_k"],
             "share": values["adjusted_revenue_k"] / total_adjusted if total_adjusted else 0.0,
             "count": values["count"]}
            for group, values in by_customer.items()
        ),
        key=lambda item: item["adjusted_revenue_k"], reverse=True,
    )

    return {
        "by_region": by_region,
        "by_stage": by_stage,
        "by_customer": by_customer,
        "by_end_customer": by_end_customer,
        "by_product_line": by_product_line,
        "by_part_number": by_part_number,
        "by_design_status": by_design_status,
        "customer_concentration": concentration,
        "total_sales_revenue_k": total_sales,
        "total_adjusted_revenue_k": total_adjusted,
        # Reported alongside, never added into the two above: a total that
        # blends silicon volume with engineering charges cannot be reconciled
        # against either source.
        "total_nre_revenue_k": total_nre,
        "total_nre_weighted_k": total_nre_weighted,
    }


def _add_group(groups: dict, key: str, financials: ProjectFinancials) -> None:
    entry = groups.setdefault(
        key, {"sales_revenue_k": 0.0, "adjusted_revenue_k": 0.0, "nre_revenue_k": 0.0, "count": 0}
    )
    entry["sales_revenue_k"] += financials.sales_revenue_k
    entry["adjusted_revenue_k"] += financials.adjusted_revenue_k
    entry["nre_revenue_k"] += financials.nre_revenue_k
    entry["count"] += 1


def quarterly_revenue(row: dict, quarterly_units: list, disty_asp: float) -> list:
    """Matches FCST_Revenue tab: quarterly revenue = quarterly units x Disty ASP
    (columns S:V = L * N:Q, or AC:AF = L * X:AA). The phasing rule that produces
    quarterly_units (flat / ramp / programme-driven) is C11, still undecided."""
    return [units * disty_asp for units in quarterly_units]
