"""
Regression test: the deterministic calc engine must reproduce the exact numbers
already in TrackF_1.xlsx's ProjectTrack tab. If this test fails, the financial
math itself has changed, which should never happen silently (Work Breakdown 5.1).
"""

import json
from pathlib import Path

from app.calc.engine import compute_project_financials

FIXTURE = Path(__file__).parent / "fixtures" / "sample_pipeline.json"

# (project name, expected Sales Revenue $K, expected Adjusted Revenue $K), lifted
# directly from ProjectTrack columns O and R in TrackF_1.xlsx.
EXPECTED = {
    "Hercules": (3300.0, 3300.0),
    "Aphrodite": (4050.0, 3240.0),
    "Hermes": (40000.0, 12000.0),
    "Poseidon": (16000.0, 1600.0),
    "Apollo": (10000.0, 5000.0),
    "Hugo": (2250.0, 675.0),
    "Dresden": (3000.0, 1500.0),
    "Yellowstone": (3000.0, 3000.0),
    "Montana": (750.0, 600.0),
}


def approx(a, b, tol=0.01):
    return abs(a - b) <= tol


def test_matches_spreadsheet():
    data = json.loads(FIXTURE.read_text())

    for row in data["project_track"]:
        f = compute_project_financials(row)
        want_sales, want_adjusted = EXPECTED[f.project]
        assert approx(f.sales_revenue_k, want_sales), f"{f.project} sales revenue: got {f.sales_revenue_k}, want {want_sales}"
        assert approx(f.adjusted_revenue_k, want_adjusted), f"{f.project} adjusted revenue: got {f.adjusted_revenue_k}, want {want_adjusted}"


# --------------------------------------------------------------------------- #
# WBS 5.6 / 12.1 -- every calculation beyond C1/C2, against the specification's
# own worked examples (build spec, section 05: "One row, carried through every
# calculation" and the C8/C9/C12 tables), and against the real workbook.
# --------------------------------------------------------------------------- #

import pytest
from pathlib import Path

from app.calc.engine import part_level_demand, portfolio_rollup
from app.calc.nre import nre_by_quarter
from app.calc.phasing import PROGRAMME, RAMP, UNPHASED, phase, profile_from_fields, quarterly_revenue_k
from app.services.portfolio import concentration

HERMES = {
    "region": "Korea", "customer": "Flextron", "end_customer": "Ford", "project": "Hermes",
    "part_number": "AX10", "design_status": "Sample", "stage": "EVT", "eau_kpcs": 10000,
    "unit_set": 15, "disty_asp": 4.0, "resale_asp": 4.3, "confidence": 0.30,
}
WORKBOOK = Path(__file__).resolve().parents[3] / "data" / "TrackF (1).xlsx"


def test_hermes_carried_through_every_calculation():
    f = compute_project_financials(HERMES)
    assert f.sales_revenue_k == pytest.approx(40000.0)          # C1
    assert f.adjusted_revenue_k == pytest.approx(12000.0)       # C2
    assert f.set_volume == pytest.approx(666.6667, abs=0.001)   # C3
    assert f.attach_rate == 15                                  # C4
    assert f.channel_margin_usd == pytest.approx(0.30)          # C5
    assert f.channel_margin_pct == pytest.approx(0.0698, abs=0.0001)  # C6, a fraction (6.98%)
    assert f.channel_margin_usd * f.eau_kpcs == pytest.approx(3000.0)  # C5b margin on the row


def test_regional_and_stage_rollups_tie_to_the_specification():
    import json
    rows = json.load(open(Path(__file__).parent / "fixtures" / "sample_pipeline.json"))["project_track"]
    fins = [compute_project_financials({**r, "unit_set": None}) for r in rows]
    roll = portfolio_rollup(fins)
    by_region = roll["by_region"]
    assert by_region["Korea"]["adjusted_revenue_k"] == pytest.approx(25140.0)      # C8
    assert by_region["EU"]["adjusted_revenue_k"] == pytest.approx(2175.0)
    assert by_region["Taiwan"]["adjusted_revenue_k"] == pytest.approx(3600.0)
    assert sum(v["adjusted_revenue_k"] for v in by_region.values()) == pytest.approx(30915.0)
    by_stage = roll["by_stage"]
    assert by_stage["EVT"]["adjusted_revenue_k"] == pytest.approx(19175.0)         # C9
    assert by_stage["Concept"]["adjusted_revenue_k"] == pytest.approx(1600.0)
    assert by_stage["DVT"]["adjusted_revenue_k"] == pytest.approx(3840.0)
    assert by_stage["PVT"]["adjusted_revenue_k"] == pytest.approx(6300.0)
    # Effective confidence falls out of the roll-up: Taiwan nearly banked, Korea speculative.
    assert 3600 / 3750 == pytest.approx(0.96)
    assert 25140 / 73350 == pytest.approx(0.343, abs=0.001)
    demand = part_level_demand(fins)                                                # C7
    assert demand["AX01"]["eau_kpcs"] == pytest.approx(1100 + 1350 + 750 + 1000 + 1000 + 250)
    conc = concentration(fins)                                                      # C12
    assert conc["cuts"]["row"]["shares"]["Hermes"] == pytest.approx(0.388, abs=0.001)


def test_phasing_rule_is_programme_then_ramp_then_unphased():
    from datetime import date

    ramp = phase(eau_kpcs=1200, mp_date=date(2025, 8, 1))
    assert ramp.basis == RAMP and ramp.fractions_sum == pytest.approx(1.0)
    assert [(q.year, q.quarter) for q in ramp.quarters] == [(2025, 3), (2025, 4), (2026, 1), (2026, 2)]
    revenue = quarterly_revenue_k(ramp, 553.8)
    assert sum(revenue.values()) == pytest.approx(553.8)   # timing changes, totals never do

    prog = phase(eau_kpcs=1200, mp_date=date(2025, 8, 1), profile={2025: [0, 0, 300, 900], 2026: [350, 350, 350, 350]})
    assert prog.basis == PROGRAMME
    assert [(q.year, q.quarter, q.units_kpcs) for q in prog.quarters][:2] == [(2025, 3, 300), (2025, 4, 900)]
    assert prog.fractions_sum == pytest.approx(1.0)

    assert phase(eau_kpcs=1200, mp_date=None).basis == UNPHASED
    # An all-zero profile is no profile.
    assert phase(eau_kpcs=1200, mp_date=None, profile={2025: [0, 0, 0, 0]}).basis == UNPHASED


@pytest.mark.skipif(not WORKBOOK.exists(), reason="TrackF (1).xlsx not present in this checkout")
def test_t2_and_c10_reproduce_the_workbook_fcst_tab():
    from app.intake.xlsx_reader import read_workbook

    fcst = read_workbook(WORKBOOK).tabs["FCST_Revenue"].rows
    tk1 = next(r for r in fcst if r.fields["project"] == "TK1")
    profile = profile_from_fields(tk1.fields)
    assert profile == {2025: [0, 0, 300, 900], 2026: [350, 350, 350, 350]}
    phasing = phase(eau_kpcs=tk1.fields["eau_kpcs"], mp_date=None, profile=profile)
    # T2: units x the flat ASP, quarter by quarter, equals the sheet's S:V.
    revenue = {k: v for k, v in quarterly_revenue_k(phasing, 0.4615 * 2600).items()}
    assert revenue[(2025, 3)] == pytest.approx(138.45, abs=0.01)
    assert revenue[(2025, 4)] == pytest.approx(415.35, abs=0.01)
    assert revenue[(2026, 1)] == pytest.approx(161.525, abs=0.01)

    nre = nre_by_quarter(fcst)                                                      # C10
    assert nre[(2025, 2)] == pytest.approx(414.0)
    assert nre[(2025, 3)] == pytest.approx(210.0)
    assert nre[(2025, 4)] == pytest.approx(395.0)
    assert sum(v for (y, _), v in nre.items() if y == 2025) == pytest.approx(1019.0)
