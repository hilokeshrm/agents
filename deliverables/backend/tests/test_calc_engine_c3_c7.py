"""
Regression tests for WBS 5.2 (C3-C7): set volume, attach rate, channel margin
($ and %), and part-level demand.

Unit-Set example values (5, 10, 15, 20) are the ones cited in
docs/03-reference/Opportunity_Tracking_Agent_Tab_and_Field_Map.docx for
ProjectTrack column L -- not fabricated, but not lifted from a fixture row
either, since Unit-Set "was dropped entirely from the POC's sample data."
"""

import pytest

from app.calc.engine import compute_project_financials, part_level_demand

BASE_ROW = {
    "project": "Hercules", "region": "Korea", "customer": "SLM",
    "design_status": "Design Win", "stage": "PVT", "part_number": "AX01",
    "eau_kpcs": 1100.0, "disty_asp": 3.0, "confidence": 1.0,
}


def test_set_volume_and_attach_rate_reconcile_with_unit_set():
    row = {**BASE_ROW, "unit_set": 10.0}
    f = compute_project_financials(row)

    assert f.set_volume == pytest.approx(110.0)  # 1100 Kpcs / 10 units-per-set
    # C4's done-when: attach rate must reconcile with the Unit-Set definition,
    # not contradict it -- round-tripping set_volume * attach_rate recovers EAU.
    assert f.attach_rate == pytest.approx(10.0)
    assert f.set_volume * f.attach_rate == pytest.approx(f.eau_kpcs)


def test_set_volume_and_attach_rate_none_without_unit_set():
    """Not invented: no Unit-Set on the row means no guessed set volume."""
    f = compute_project_financials(BASE_ROW)
    assert f.set_volume is None
    assert f.attach_rate is None


def test_set_volume_and_attach_rate_none_when_unit_set_is_zero():
    f = compute_project_financials({**BASE_ROW, "unit_set": 0})
    assert f.set_volume is None
    assert f.attach_rate is None


def test_channel_margin_usd_and_pct():
    row = {**BASE_ROW, "resale_asp": 3.2}  # disty_asp is 3.0 in BASE_ROW
    f = compute_project_financials(row)

    assert f.channel_margin_usd == pytest.approx(0.2)
    assert f.channel_margin_pct == pytest.approx(0.2 / 3.2)


def test_channel_margin_none_without_resale_asp():
    f = compute_project_financials(BASE_ROW)
    assert f.channel_margin_usd is None
    assert f.channel_margin_pct is None


def test_part_level_demand_aggregates_across_projects():
    rows = [
        {**BASE_ROW, "project": "Hercules", "part_number": "AX01", "eau_kpcs": 1100.0},
        {**BASE_ROW, "project": "Aphrodite", "part_number": "AX01", "eau_kpcs": 1350.0},
        {**BASE_ROW, "project": "Yellowstone", "part_number": "AX01", "eau_kpcs": 1000.0},
        {**BASE_ROW, "project": "Hermes", "part_number": "AX10", "eau_kpcs": 10000.0},
    ]
    financials = [compute_project_financials(r) for r in rows]
    demand = part_level_demand(financials)

    assert demand["AX01"]["eau_kpcs"] == pytest.approx(1100.0 + 1350.0 + 1000.0)
    assert set(demand["AX01"]["projects"]) == {"Hercules", "Aphrodite", "Yellowstone"}
    assert demand["AX10"]["eau_kpcs"] == pytest.approx(10000.0)
    assert demand["AX10"]["projects"] == ["Hermes"]


def test_portfolio_rollup_exposes_dimensions_and_customer_concentration():
    from app.calc.engine import portfolio_rollup

    rows = [
        {**BASE_ROW, "project": "Hercules", "customer": "SLM", "end_customer": "GM", "product_line": "SerDes", "eau_kpcs": 100.0, "confidence": 1.0},
        {**BASE_ROW, "project": "Apollo", "customer": "Flextron", "end_customer": "Ford", "product_line": "LED", "eau_kpcs": 50.0, "confidence": 0.5},
    ]
    result = portfolio_rollup([compute_project_financials(row) for row in rows])

    assert result["by_customer"]["SLM"]["adjusted_revenue_k"] == pytest.approx(300.0)
    assert result["by_end_customer"]["Ford"]["count"] == 1
    assert result["by_product_line"]["LED"]["adjusted_revenue_k"] == pytest.approx(75.0)
    assert result["by_design_status"]["Design Win"]["count"] == 2
    assert result["customer_concentration"][0]["group"] == "SLM"
    assert result["customer_concentration"][0]["share"] == pytest.approx(300 / 375)
