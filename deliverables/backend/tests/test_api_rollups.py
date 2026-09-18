"""
API regression tests for the computed rollup endpoints (accounts, products,
reports, dashboard). None of these back a stored table -- each groups the same
live opportunity rows a different way.
"""

import pytest

WON = {
    "region": "Korea", "customer": "SLM", "end_customer": "GM", "project": "Hercules",
    "product_line": "SerDes", "part_number": "AX01", "design_status": "Design Win", "stage": "PVT",
    "mp_date": "2026-09-01", "eau_kpcs": 1100, "unit_set": 10, "disty_asp": 3, "resale_asp": 3.2,
    "confidence": 1.0, "competitor_part": "BD83740", "owner": "jdoe", "confidence_rationale": "locked",
}

OPEN = {
    "region": "Korea", "customer": "SLM", "end_customer": "GM", "project": "Aphrodite",
    "product_line": "SerDes", "part_number": "AX01", "design_status": "Design In", "stage": "DVT",
    "mp_date": "2027-02-01", "eau_kpcs": 1350, "disty_asp": 3, "confidence": 0.8,
    "owner": "jdoe", "confidence_rationale": "in progress",
}

OTHER_ACCOUNT = {
    "region": "EU", "customer": "ODE", "end_customer": "BMWi", "project": "Hugo",
    "product_line": "SerDes", "part_number": "AX02", "design_status": "Evaluation", "stage": "EVT",
    "eau_kpcs": 750, "disty_asp": 3, "confidence": 0.3, "owner": "jdoe", "confidence_rationale": "early",
}


def _seed(client):
    for payload in (WON, OPEN, OTHER_ACCOUNT):
        resp = client.post("/api/v1/opportunities", json=payload)
        assert resp.status_code == 201, resp.json()


def test_accounts_rollup(client):
    _seed(client)
    accounts = client.get("/api/v1/accounts").json()
    names = {a["name"] for a in accounts}
    assert names == {"SLM", "ODE"}

    slm = next(a for a in accounts if a["name"] == "SLM")
    assert slm["opportunity_count"] == 2
    assert slm["closed_won_k"] == pytest.approx(3300.0)  # Hercules: 1100 * 3 * 1.0
    assert slm["open_pipeline_k"] == pytest.approx(1350 * 3 * 0.8)  # Aphrodite

    detail = client.get("/api/v1/accounts/SLM").json()
    assert detail["parts_in_play"] == 1  # both SLM opportunities share AX01
    assert detail["pipeline_by_product_line"]["SerDes"] == pytest.approx(3300.0 + 1350 * 3 * 0.8)


def test_account_not_found(client):
    assert client.get("/api/v1/accounts/does-not-exist").status_code == 404


def test_products_rollup(client):
    _seed(client)
    products = client.get("/api/v1/products").json()
    ax01 = next(p for p in products if p["part_number"] == "AX01")
    assert ax01["opportunity_count"] == 2
    assert ax01["combined_eau_kpcs"] == pytest.approx(1100 + 1350)
    assert ax01["margin_pct"] == pytest.approx((3.2 - 3.0) / 3.2)  # from WON, the only row with resale_asp

    detail = client.get("/api/v1/products/AX01").json()
    assert len(detail["opportunities"]) == 2


def test_reports_list_and_run(client):
    _seed(client)
    reports = client.get("/api/v1/reports").json()
    assert {r["id"] for r in reports} == {"design_status", "stage", "product_line", "region", "competitor", "mp_year"}

    result = client.get("/api/v1/reports/design_status").json()
    assert result["record_count"] == 3
    groups = {g["group"]: g for g in result["groups"]}
    assert groups["Design Win"]["opportunity_count"] == 1
    assert groups["Design Win"]["total_amount_k"] == pytest.approx(3300.0)
    assert result["grand_total_k"] == pytest.approx(sum(g["total_amount_k"] for g in result["groups"]))


def test_report_unknown_id_404(client):
    assert client.get("/api/v1/reports/bogus").status_code == 404


def test_dashboard_summary(client):
    _seed(client)
    d = client.get("/api/v1/dashboard").json()

    assert d["opportunity_count"] == 3
    assert d["closed_won_k"] == pytest.approx(3300.0)
    assert d["open_pipeline_k"] == pytest.approx(1350 * 3 * 0.8 + 750 * 3 * 0.3)
    assert d["total_pipeline_k"] == pytest.approx(d["open_pipeline_k"] + d["closed_won_k"])
    # Amount x confidence, applied once. The tile that renders this used to show
    # sales x confidence squared, which is lower than the truth and means nothing.
    expected_weighted = sum(o["adjusted_revenue_k"] for o in client.get("/api/v1/opportunities").json())
    assert d["weighted_forecast_k"] == pytest.approx(expected_weighted)
    assert d["total_nre_revenue_k"] == pytest.approx(
        sum(o["nre_revenue_k"] for o in client.get("/api/v1/opportunities").json())
    )

    by_status = {b["design_status"]: b for b in d["funnel_by_design_status"]}
    assert by_status["Design Win"]["count"] == 1
    assert "SerDes" in d["pipeline_by_product_line"]
    assert "2026" in d["pipeline_by_mp_year"] or "No M/P date" in d["pipeline_by_mp_year"]
