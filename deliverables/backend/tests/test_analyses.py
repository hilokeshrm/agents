"""
Analyses (WBS 6.1-6.6), the stall sweep (8.5) and notifications (11.7).

Done-whens: adding an analysis needs only a `requires` declaration (6.1);
each analysis produces a figure a reviewer can act on and names its rows
(6.2); coverage and accuracy are dark until their input exists and light up
when it does (6.4, 6.5); two runs compare with every difference attributed
(6.6); stalls and overdue milestones become findings with the rationale
attached (8.5) and reach the owner (11.7).
"""

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import update

from app.db.models.actual import Actual
from app.db.models.state_history import StateHistory
from tests.test_judgment_layer import load_nine
from tests.test_roles_and_scope import PAYLOAD, headers


def analyses(client, role="director"):
    body = client.get("/api/v1/analyses", headers=headers(role)).json()
    return {a["key"]: a for a in body["ran"]}, {a["key"]: a for a in body["dark"]}, body


# --------------------------------------------------------------------------- #
# 6.1 / 6.2
# --------------------------------------------------------------------------- #

def test_the_catalogue_is_discovered_not_registered(client):
    keys = {a["key"] for a in client.get("/api/v1/analyses/catalogue").json()}
    assert keys >= {"stage_mix", "concentration_risk", "data_quality", "milestones_and_stalls",
                    "competitive_exposure", "channel_margin", "coverage", "forecast_accuracy", "owner_calibration"}


def test_six_analyses_run_on_the_nine_rows_and_name_their_rows(client):
    load_nine(client)
    ran, dark, body = analyses(client)
    assert body["scorable_rows"] == 9

    sm = ran["stage_mix"]
    # Concept + EVT = (1,600 + 19,175) / 30,915: "two-thirds of the weighted pipeline has not reached DVT".
    assert sm["figures"]["early_share_of_weighted"] == pytest.approx(0.672, abs=0.001)
    assert sm["figures"]["top_heavy"] is True
    assert "not reached DVT" in sm["headline"]
    assert next(r for r in sm["rows"] if r["stage"] == "EVT")["projects"] == ["Hermes", "Apollo", "Hugo", "Dresden"]

    cr = ran["concentration_risk"]
    assert "Korea is 81%" in cr["headline"] or cr["figures"]["cuts"]["region"]["share"] == pytest.approx(0.813, abs=0.001)
    assert {r["project"] for r in cr["rows"]} == {"Hermes", "Yellowstone", "Hugo", "Dresden"}

    dq = ran["data_quality"]
    assert dq["figures"]["clean_rows"] == 9

    ms = ran["milestones_and_stalls"]
    assert ms["status"] in ("live", "partial")

    ce = ran["competitive_exposure"]
    assert ce["status"] == "partial" and ce["figures"]["sockets_with_rival"] == 0

    cm = ran["channel_margin"]
    assert cm["figures"]["priced_rows"] == 9
    assert cm["rows"][0]["project"] == "Hermes"          # largest margin on the row: $0.30 x 10,000
    assert cm["rows"][0]["margin_on_row_k"] == pytest.approx(3000.0)

    # The three that wait on data say which parameter they wait on.
    assert dark["coverage"]["missing"] == ["G1", "G2"]
    assert "Regional Target" in dark["coverage"]["note"]
    assert set(dark["forecast_accuracy"]["missing"]) == {"A1", "A3"}
    assert set(dark["owner_calibration"]["missing"]) == {"H3", "O1"}


# --------------------------------------------------------------------------- #
# 6.4 -- coverage lights up when Finance enters a target
# --------------------------------------------------------------------------- #

def test_coverage_is_dark_until_finance_enters_a_target_then_computes(client):
    load_nine(client)
    assert client.put("/api/v1/targets", json={"region": "Korea", "period": "2027", "amount_k": 10000},
                      headers=headers("director")).status_code == 403
    with client.session_factory() as db:
        from app.db.models.opportunity import Opportunity
        for name, mp in (("Aphrodite", date(2027, 2, 1)), ("Apollo", date(2027, 6, 1))):
            db.execute(update(Opportunity).where(Opportunity.project == name).values(mp_date=mp))
        db.commit()
    resp = client.put("/api/v1/targets", json={"region": "KR", "period": "2027", "amount_k": 10000},
                      headers=headers("finance", "*", "cfo"))
    assert resp.status_code == 200 and resp.json()["region"] == "Korea"
    ran, dark, body = analyses(client)
    assert "coverage" not in dark and "G1" in body["available_parameters"]
    row = next(r for r in ran["coverage"]["rows"] if r["region"] == "Korea" and r["period"] == "2027")
    # Korea rows with M/P in 2027 phase into 2027: Aphrodite (Feb'27, ramp Q1-Q4 = all) and Apollo (Jun'27,
    # Q2-Q4 plus Q1'28 => 60% in 2027): 3240 + 5000*0.6 = 6240.
    assert row["weighted_pipeline_k"] == pytest.approx(3240 + 5000 * 0.6)
    assert row["coverage"] == pytest.approx(row["weighted_pipeline_k"] / 10000)


# --------------------------------------------------------------------------- #
# 6.5 -- accuracy and calibration light up with actuals and outcomes
# --------------------------------------------------------------------------- #

def test_forecast_accuracy_computes_against_an_actual(client):
    ids = load_nine(client)
    with client.session_factory() as db:
        from app.db.models.opportunity import Opportunity
        db.execute(update(Opportunity).where(Opportunity.project == "Hercules").values(mp_date=date(2026, 9, 1)))
        # Hercules: 1,100 Kpcs x $3 with M/P Sep'26 -> ramp Q3'26 10% = $330K forecast.
        db.add(Actual(part_number="AX01", region="Korea", year=2026, quarter=3, source="erp", revenue_k=300.0,
                      pull_ref="erp-2026-10"))
        db.commit()
    ran, dark, _ = analyses(client)
    fa = ran["forecast_accuracy"]
    row = next(r for r in fa["rows"] if r["period"] == "2026-Q3")
    # Q3'26 forecast for AX01: Hercules 3300*0.10 + Yellowstone (Oct'26) 0 => 330; error (330-300)/330.
    assert row["forecast_revenue_k"] == pytest.approx(330.0)
    assert row["error"] == pytest.approx(30 / 330)
    assert fa["figures"]["bias_by_region"]["Korea"] == pytest.approx(30 / 330)


def test_calibration_rebuild_needs_five_outcomes_and_two_quarters(client):
    from app.services.calibration import rebuild_calibration, resolved_outcomes

    # Six rows owned by jdoe, resolved: four won at 0.9, two lost at 0.7.
    rows = []
    for i in range(6):
        rows.append(client.post("/api/v1/opportunities", json={
            **PAYLOAD, "project": f"P{i}", "design_status": "Design In", "stage": "DVT",
            "confidence": 0.9 if i < 4 else 0.7,
        }, headers=headers("director")).json())
    for i, r in enumerate(rows):
        body = {"field": "design_status", "actor": "marc",
                **({"to_value": "Mass Production"} if i < 4 else {"to_value": "Lost", "reason_code": "price"})}
        assert client.post(f"/api/v1/opportunities/{r['id']}/transition", json=body, headers=headers("director")).status_code == 201

    with client.session_factory() as db:
        outcomes = resolved_outcomes(db)
        assert len(outcomes) == 6
        written = rebuild_calibration(db, as_of=date.today())
        db.commit()
        jdoe = next(c for c in written if c.owner == "jdoe")
        # bias = mean(conf - outcome) = (4*(0.9-1) + 2*(0.7-0)) / 6 = (-0.4 + 1.4)/6 = +16.7pp
        assert jdoe.bias_pp == pytest.approx(16.67, abs=0.05)
        assert jdoe.sample_size == 6
        assert jdoe.reliable is False  # everything resolved today: no two quarters of history yet
        # Backdate the closes by seven months (Core statement: state_history is append-only via the ORM).
        db.execute(update(StateHistory).values(occurred_at=datetime.now(timezone.utc) - timedelta(days=200)))
        db.commit()
        again = rebuild_calibration(db, as_of=date.today())
        db.commit()
        assert next(c for c in again if c.owner == "jdoe").reliable is True

    ran, dark, _ = analyses(client)
    assert "owner_calibration" not in dark
    oc = ran["owner_calibration"]
    assert "jdoe runs +17pp" in oc["headline"]
    # +16.7pp against a 37.7pp spread is inside one standard deviation: J-06 would not fire.
    assert next(r for r in oc["rows"] if r["owner"] == "jdoe")["reads"] == "calibrated"


# --------------------------------------------------------------------------- #
# 6.6 -- run-to-run comparison
# --------------------------------------------------------------------------- #

def test_two_runs_over_the_same_rows_compare_identical_and_a_rubric_change_is_attributed(client):
    load_nine(client)
    client.post("/api/v1/rubric/publish-v1", headers=headers("admin"))
    a = client.post("/api/v1/runs", json={}, headers=headers("admin")).json()
    # Resolve every proposal so the second run scores the same rows again.
    for p in client.get("/api/v1/proposals", headers=headers("director")).json():
        client.post(f"/api/v1/proposals/{p['id']}/resolve", json={"action": "reject", "reason_code": "other"},
                    headers=headers("director", "*", "marc"))
    b = client.post("/api/v1/runs", json={}, headers=headers("admin")).json()
    cmp = client.get(f"/api/v1/runs/{a['id']}/compare/{b['id']}", headers=headers("director")).json()
    assert cmp["identical"] is True and cmp["stamp_differences"] == [] and cmp["unattributed_differences"] == 0
    assert len(cmp["rows"]) == 9

    # Publish a version that disables J-05, resolve, run again: the difference is attributed to the rubric.
    draft = client.get("/api/v1/rubric/draft").json()
    for f in draft["rubric_factors"]["factors"]:
        if f["key"] == "customer_concentration":
            f["enabled"] = False
    client.post("/api/v1/rubric/versions", json={"label": "no-J05", **{k: draft[k] for k in ("matrix_a", "rubric_factors")}},
                headers=headers("admin"))
    for p in client.get("/api/v1/proposals", headers=headers("director")).json():
        client.post(f"/api/v1/proposals/{p['id']}/resolve", json={"action": "reject", "reason_code": "other"},
                    headers=headers("director", "*", "marc"))
    c = client.post("/api/v1/runs", json={}, headers=headers("admin")).json()
    cmp = client.get(f"/api/v1/runs/{b['id']}/compare/{c['id']}", headers=headers("director")).json()
    assert cmp["identical"] is False and cmp["stamp_differences"] == ["rubric_version"]
    hermes = next(r for r in cmp["rows"] if r["project"] == "Hermes")
    assert hermes["a_rules"] == ["J-05"] and hermes["b_rules"] == [] and hermes["attributed_to"] == ["rubric_version"]
    assert cmp["unattributed_differences"] == 0


# --------------------------------------------------------------------------- #
# 8.5 / 11.7 -- the sweep and its notifications
# --------------------------------------------------------------------------- #

def test_nightly_sweep_raises_findings_and_notifies_the_owner(client):
    opp = client.post("/api/v1/opportunities", json={
        **PAYLOAD, "design_status": "Evaluation", "stage": "EVT", "confidence": 0.35,
        "evidence": "PPAP: Oct'25, Design Review: Jul'25",
    }, headers=headers("director")).json()
    # Give the portfolio a median: two other rows that completed an EVT visit in 30 days.
    for name in ("A", "B"):
        other = client.post("/api/v1/opportunities", json={**PAYLOAD, "project": name, "design_status": "Evaluation",
                                                            "stage": "EVT", "confidence": 0.35}, headers=headers("director")).json()
        client.post(f"/api/v1/opportunities/{other['id']}/transition",
                    json={"field": "stage", "to_value": "DVT", "actor": "marc", "reason_code": "advanced_to_next_stage"},
                    headers=headers("director"))
    with client.session_factory() as db:
        # Backdate: the two EVT visits lasted 30 days; the subject has sat 100 days.
        seeds = db.query(StateHistory).filter(StateHistory.field == "stage", StateHistory.from_value.is_(None)).all()
        for s in seeds:
            days = 100 if s.opportunity_id == opp["id"] else 30
            db.execute(update(StateHistory).where(StateHistory.id == s.id)
                       .values(occurred_at=datetime.now(timezone.utc) - timedelta(days=days)))
        db.commit()

    result = client.post("/api/v1/sweeps/nightly", headers=headers("admin")).json()
    assert result["stalls"] == 1 and result["overdue_milestones"] == 2
    assert result["findings"] == 3

    audit = client.get(f"/api/v1/audit?opportunity_id={opp['id']}", headers=headers("director")).json()
    kinds = {e["summary"] for e in audit if e["source"] == "finding"}
    assert {"STALL", "MILESTONE"} <= kinds

    mine = client.get("/api/v1/notifications", headers=headers("owner", "*", "jdoe")).json()
    assert {n["kind"] for n in mine} == {"stall", "milestone"}
    assert any("PPAP" in n["subject"] for n in mine)

    # A second sweep the same day writes nothing new.
    again = client.post("/api/v1/sweeps/nightly", headers=headers("admin")).json()
    assert again["findings"] == 0 and again["notifications"] == 0

    dispatched = client.post("/api/v1/notifications/dispatch", headers=headers("admin")).json()
    assert dispatched["channel"] == "log" and dispatched["failed"] == 0 and dispatched["sent"] >= 3
    assert all(n["status"] == "sent" for n in client.get("/api/v1/notifications", headers=headers("admin")).json())
