"""
NRE kept beside silicon volume revenue, never inside it (WBS 3.5, 5.4).

app/calc/nre.py already split the workbook's own NRE rows. This is the same
principle applied to a live opportunity: a one-off engineering charge is
recorded on the row, reported in its own column, and recognised whole in the M/P
quarter rather than ramped like silicon shipping into a programme.

The test that matters most is the last one: adding NRE to a row must not move a
single volume figure. If it does, NRE is hiding inside revenue again and every
downstream quarter is wrong.
"""

import pytest

from app.calc.engine import compute_project_financials, portfolio_rollup
from tests.test_roles_and_scope import PAYLOAD, headers

NRE_PAYLOAD = {**PAYLOAD, "project": "Hermes NRE", "nre_charge_k": 126.0, "mp_date": "2026-12-01"}


def _row(**overrides) -> dict:
    base = {
        "project": "X", "region": "Korea", "customer": "Mobis", "design_status": "Design Win",
        "stage": "PVT", "part_number": "AX01", "eau_kpcs": 1000, "disty_asp": 3, "confidence": 0.5,
    }
    return {**base, **overrides}


# --------------------------------------------------------------------------- #
# The engine
# --------------------------------------------------------------------------- #

def test_nre_is_carried_beside_volume_revenue_not_inside_it():
    financials = compute_project_financials(_row(nre_charge_k=126.0))

    assert financials.sales_revenue_k == pytest.approx(3000.0)      # 1000 x 3, unchanged
    assert financials.adjusted_revenue_k == pytest.approx(1500.0)   # x 0.5, unchanged
    assert financials.nre_revenue_k == pytest.approx(126.0)
    assert financials.nre_weighted_k == pytest.approx(63.0)


def test_a_row_without_nre_reports_zero_not_none():
    """None and 0.0 are the same figure here: a row with no NRE contributes
    nothing either way, and a null would propagate through every total."""
    financials = compute_project_financials(_row())
    assert financials.nre_revenue_k == 0.0
    assert financials.nre_weighted_k == 0.0


def test_rollup_totals_keep_the_two_apart():
    rollup = portfolio_rollup([
        compute_project_financials(_row(project="A", nre_charge_k=126.0)),
        compute_project_financials(_row(project="B")),
    ])

    assert rollup["total_sales_revenue_k"] == pytest.approx(6000.0)
    assert rollup["total_adjusted_revenue_k"] == pytest.approx(3000.0)
    assert rollup["total_nre_revenue_k"] == pytest.approx(126.0)
    assert rollup["total_nre_weighted_k"] == pytest.approx(63.0)
    # NRE appears per group as well, so a regional total cannot quietly omit it.
    assert rollup["by_region"]["Korea"]["nre_revenue_k"] == pytest.approx(126.0)


# --------------------------------------------------------------------------- #
# Through the API
# --------------------------------------------------------------------------- #

def test_intake_stores_the_charge_and_the_read_model_reports_it(client):
    created = client.post("/api/v1/opportunities", json=NRE_PAYLOAD, headers=headers("director")).json()

    assert created["nre_charge_k"] == 126.0
    assert created["nre_revenue_k"] == 126.0
    assert created["nre_weighted_k"] == pytest.approx(126.0)  # confidence 1.0 on this payload
    assert created["sales_revenue_k"] == pytest.approx(3300.0)


def test_the_charge_carries_provenance_like_every_other_value(client):
    """A field the calc engine reads must reach it with a source attached, or
    wrap_row raises rather than letting it through unprovenanced (WBS 3.6)."""
    created = client.post("/api/v1/opportunities", json=NRE_PAYLOAD, headers=headers("director")).json()
    rows = client.get(f"/api/v1/opportunities/{created['id']}/provenance").json()

    by_param = {r["param"]: r for r in rows}
    assert by_param["V29"]["name"] == "NRE Charge"
    assert by_param["V29"]["value"] == "126.0"
    assert by_param["V29"]["source"] == "direct_entry"


def test_forecast_feed_recognises_nre_whole_at_the_mp_quarter(client):
    """The ramp models silicon shipping into a programme. A one-off engineering
    charge does not ramp, so it lands entirely in the M/P quarter."""
    client.post("/api/v1/opportunities", json=NRE_PAYLOAD, headers=headers("director"))

    feed = client.get("/api/v1/forecast-feed", headers=headers("finance")).json()
    quarters = {q["label"]: q for q in feed["quarters"]}

    assert feed["nre_rule"] == "recognised_whole_at_mp_quarter"
    assert quarters["2026 Q4"]["nre_revenue_k"] == pytest.approx(126.0)
    # Not spread across the following three quarters, unlike the volume revenue.
    assert [quarters[label]["nre_revenue_k"] for label in ("2027 Q1", "2027 Q2", "2027 Q3")] == [0.0, 0.0, 0.0]
    assert [quarters[label]["weighted_revenue_k"] > 0 for label in ("2027 Q1", "2027 Q2", "2027 Q3")] == [True] * 3


def test_nre_is_never_added_into_the_weighted_volume_total(client):
    client.post("/api/v1/opportunities", json=NRE_PAYLOAD, headers=headers("director"))
    feed = client.get("/api/v1/forecast-feed", headers=headers("finance")).json()

    phased_volume = sum(q["weighted_revenue_k"] for q in feed["quarters"])
    assert feed["total_weighted_k"] == pytest.approx(phased_volume + feed["unphased_weighted_k"])
    assert feed["total_nre_revenue_k"] == pytest.approx(126.0)
    # The volume total is exactly EAU x ASP x confidence -- no NRE in it.
    assert feed["total_weighted_k"] == pytest.approx(3300.0)


def test_adding_nre_moves_no_volume_figure(client):
    """The regression that matters: NRE must be additive information, not a
    change to any number that existed before it."""
    plain = client.post("/api/v1/opportunities", json=PAYLOAD, headers=headers("director")).json()
    before = client.get("/api/v1/dashboard", headers=headers("director")).json()

    client.post("/api/v1/opportunities",
                json={**NRE_PAYLOAD, "project": "NRE only", "eau_kpcs": 1, "disty_asp": 1, "confidence": 0.0},
                headers=headers("director"))
    after = client.get("/api/v1/dashboard", headers=headers("director")).json()

    assert after["weighted_forecast_k"] == pytest.approx(before["weighted_forecast_k"])
    assert client.get(f"/api/v1/opportunities/{plain['id']}").json()["adjusted_revenue_k"] == pytest.approx(
        plain["adjusted_revenue_k"]
    )
