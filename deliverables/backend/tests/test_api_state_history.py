"""
API regression tests for the state_history endpoints (WBS 9.2): transitioning an
opportunity, reading its event stream, time-in-stage, and the win-rate analytic.
"""

import pytest

PAYLOAD = {
    "region": "Korea", "customer": "SLM", "end_customer": "GM", "project": "Hercules",
    "part_number": "AX01", "design_status": "Evaluation", "stage": "EVT",
    "eau_kpcs": 1100, "disty_asp": 3, "confidence": 0.5,
    "owner": "jdoe", "confidence_rationale": "under evaluation",
}


def _create(client, **overrides):
    payload = {**PAYLOAD, **overrides}
    resp = client.post("/api/v1/opportunities", json=payload)
    assert resp.status_code == 201
    return resp.json()


def test_create_seeds_state_history(client):
    opp = _create(client)
    history = client.get(f"/api/v1/opportunities/{opp['id']}/state-history")
    assert history.status_code == 200
    events = history.json()
    assert {e["field"] for e in events} == {"design_status", "stage"}
    assert all(e["from_value"] is None for e in events)


def test_transition_updates_opportunity_and_appends_event(client):
    opp = _create(client)

    resp = client.post(
        f"/api/v1/opportunities/{opp['id']}/transition",
        json={"field": "stage", "to_value": "DVT", "actor": "jdoe", "reason_code": "advanced_to_next_stage"},
    )
    assert resp.status_code == 201
    event = resp.json()
    assert event["from_value"] == "EVT"
    assert event["to_value"] == "DVT"

    fetched = client.get(f"/api/v1/opportunities/{opp['id']}").json()
    assert fetched["stage"] == "DVT"

    history = client.get(f"/api/v1/opportunities/{opp['id']}/state-history").json()
    stage_events = [e for e in history if e["field"] == "stage"]
    assert len(stage_events) == 2


def test_time_in_stage_endpoint(client):
    opp = _create(client)
    resp = client.get(f"/api/v1/opportunities/{opp['id']}/time-in-stage")
    assert resp.status_code == 200
    body = resp.json()
    assert body["stage"] == "EVT"
    assert body["days_in_stage"] < 0.01


def test_win_rate_endpoint(client):
    won = _create(client, project="Hercules", owner="alice")
    lost = _create(client, project="Poseidon", owner="alice")
    _create(client, project="Apollo", owner="bob")  # stays open

    client.post(
        f"/api/v1/opportunities/{won['id']}/transition",
        json={"field": "design_status", "to_value": "Design Win", "actor": "alice"},
    )
    client.post(
        f"/api/v1/opportunities/{lost['id']}/transition",
        json={"field": "design_status", "to_value": "Lost", "actor": "alice", "reason_code": "price"},
        headers={"X-OppTrack-Role": "manager", "X-OppTrack-Regions": "Korea", "X-OppTrack-Actor": "manager"},
    )

    overall = client.get("/api/v1/analytics/win-rate").json()
    assert overall == {"won": 1, "lost": 1, "resolved": 2, "rate": pytest.approx(0.5)}

    alice_only = client.get("/api/v1/analytics/win-rate", params={"owner": "alice"}).json()
    assert alice_only["resolved"] == 2

    bob_only = client.get("/api/v1/analytics/win-rate", params={"owner": "bob"}).json()
    assert bob_only == {"won": 0, "lost": 0, "resolved": 0, "rate": None}


def test_transition_unknown_opportunity_404(client):
    resp = client.post(
        "/api/v1/opportunities/does-not-exist/transition",
        json={"field": "stage", "to_value": "DVT", "actor": "jdoe"},
    )
    assert resp.status_code == 404


def test_transition_invalid_reason_code_is_a_clean_400(client):
    opp = _create(client)
    resp = client.post(
        f"/api/v1/opportunities/{opp['id']}/transition",
        json={"field": "stage", "to_value": "DVT", "actor": "jdoe", "reason_code": "not_a_real_code"},
    )
    assert resp.status_code == 400
    assert "stage_exit_reason" in resp.json()["detail"]


def test_owner_cannot_close_design_lost_or_mass_production(client):
    opp = _create(client)
    lost = client.post(
        f"/api/v1/opportunities/{opp['id']}/transition",
        json={"field": "design_status", "to_value": "Lost", "actor": "jdoe", "reason_code": "price"},
        headers={"X-OppTrack-Role": "owner", "X-OppTrack-Regions": "Korea", "X-OppTrack-Actor": "jdoe"},
    )
    assert lost.status_code == 403

    mass_production = client.post(
        f"/api/v1/opportunities/{opp['id']}/transition",
        json={"field": "design_status", "to_value": "Mass Production", "actor": "jdoe"},
        headers={"X-OppTrack-Role": "owner", "X-OppTrack-Regions": "Korea", "X-OppTrack-Actor": "jdoe"},
    )
    assert mass_production.status_code == 403


def test_lost_requires_reason_code(client):
    opp = _create(client)
    response = client.post(
        f"/api/v1/opportunities/{opp['id']}/transition",
        json={"field": "design_status", "to_value": "Lost", "actor": "manager"},
        headers={"X-OppTrack-Role": "manager", "X-OppTrack-Regions": "Korea", "X-OppTrack-Actor": "manager"},
    )
    assert response.status_code == 400
    assert "loss_reason" in response.json()["detail"]
