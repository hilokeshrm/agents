"""
Lifecycle transition proposals (WBS 8.3) and sequential Opportunity IDs (WBS 2.4).

8.3 done-when: the agreed gate is implemented, and a close cannot happen
without whatever sign-off the policy requires. The policy (decision #36) is
that the agent proposes and a person with the close grant approves; a Lost
approval also has to carry the loss reason (8.4).
"""

from datetime import date

import pytest

from tests.test_roles_and_scope import PAYLOAD, headers


def create(client, **over):
    resp = client.post("/api/v1/opportunities", json={**PAYLOAD, **over}, headers=headers("director"))
    assert resp.status_code == 201, resp.text
    return resp.json()


def run(client):
    client.post("/api/v1/rubric/publish-v1", headers=headers("admin"))
    return client.post("/api/v1/runs", json={}, headers=headers("admin")).json()


def transition_proposals(client):
    return [p for p in client.get("/api/v1/proposals", headers=headers("director")).json() if p["kind"] == "transition"]


# --------------------------------------------------------------------------- #
# 8.3
# --------------------------------------------------------------------------- #

def test_a_started_design_win_gets_a_mass_production_proposal_not_a_move(client):
    won = create(client, project="Zeus", mp_date="2025-12-01")           # Design Win at PVT, M/P passed
    not_yet = create(client, project="Hercules", mp_date="2099-01-01")   # M/P in the future
    run_result = run(client)
    assert run_result["counts"]["transition_proposals"] == 1

    proposals = transition_proposals(client)
    assert len(proposals) == 1
    p = proposals[0]
    assert p["opportunity_id"] == won["id"]
    assert p["transition"]["to_value"] == "Mass Production"
    assert p["transition"]["requires_reason_code"] is False
    assert p["proposed_confidence"] == p["base_confidence"]        # moves no number
    # Nothing moved: the row still reads Design Win until a person approves.
    assert client.get(f"/api/v1/opportunities/{won['id']}").json()["design_status"] == "Design Win"
    assert client.get(f"/api/v1/opportunities/{not_yet['id']}").json()["design_status"] == "Design Win"
    lifecycle = next(s for s in run_result["steps"] if s["name"] == "Lifecycle")
    assert "Zeus -> Mass Production" in lifecycle["detail"]


def test_evidence_saying_lost_gets_a_lost_proposal_that_needs_a_reason_on_approval(client):
    opp = create(client, project="Titan", design_status="Design In", stage="DVT", confidence=0.65,
                 evidence="Customer confirmed the socket was awarded to TI in March.")
    run(client)
    p = transition_proposals(client)[0]
    assert p["transition"]["to_value"] == "Lost"
    assert p["transition"]["requires_reason_code"] is True
    assert p["transition"]["evidence_quote"].lower() == "awarded to"

    url = f"/api/v1/proposals/{p['id']}/resolve"
    no_reason = client.post(url, json={"action": "approve"}, headers=headers("director", "*", "marc"))
    assert no_reason.status_code == 400 and "loss_reason" in no_reason.json()["detail"]

    ok = client.post(url, json={"action": "approve", "reason_code": "competitor"},
                     headers=headers("director", "*", "marc"))
    assert ok.status_code == 200 and ok.json()["status"] == "approved"
    after = client.get(f"/api/v1/opportunities/{opp['id']}").json()
    assert after["design_status"] == "Lost"
    # The close is a state_history row with the approver as actor and the reason.
    history = client.get(f"/api/v1/opportunities/{opp['id']}/state-history").json()
    last = history[-1]
    assert (last["to_value"], last["actor"], last["reason_code"]) == ("Lost", "marc", "competitor")


def test_a_close_cannot_happen_without_the_close_grant(client):
    """The gate is identical whether a person or the agent starts the move:
    an owner cannot approve it, a Korea manager cannot approve an EU row, and
    the row's own owner cannot approve it either."""
    create(client, project="Zeus", mp_date="2025-12-01", region="Europe", customer="ODE", owner="jdoe")
    run(client)
    p = transition_proposals(client)[0]
    url = f"/api/v1/proposals/{p['id']}/resolve"

    assert client.post(url, json={"action": "approve"}, headers=headers("owner", "*", "kim")).status_code == 403
    assert client.post(url, json={"action": "approve"}, headers=headers("manager", "Korea", "kim")).status_code == 404
    own = client.post(url, json={"action": "approve"}, headers=headers("director", "*", "jdoe"))
    assert own.status_code == 400 and "own" in own.json()["detail"]
    assert client.post(url, json={"action": "override", "value": 0.5, "reason_code": "other"},
                       headers=headers("director", "*", "marc")).status_code == 400

    ok = client.post(url, json={"action": "approve"}, headers=headers("manager", "Europe", "lena"))
    assert ok.status_code == 200
    assert client.get(f"/api/v1/opportunities/{p['opportunity_id']}").json()["design_status"] == "Mass Production"


def test_a_rejected_transition_leaves_the_row_and_is_not_re_proposed_while_open(client):
    create(client, project="Zeus", mp_date="2025-12-01")
    run(client)
    p = transition_proposals(client)[0]
    # A second run does not double-queue while the first is pending.
    assert run(client)["counts"]["transition_proposals"] == 0
    client.post(f"/api/v1/proposals/{p['id']}/resolve",
                json={"action": "reject", "reason_code": "data_error_on_row"},
                headers=headers("director", "*", "marc"))
    assert client.get(f"/api/v1/opportunities/{p['opportunity_id']}").json()["design_status"] == "Design Win"


# --------------------------------------------------------------------------- #
# 2.4
# --------------------------------------------------------------------------- #

def test_opportunity_ids_are_sequential_and_human_readable(client):
    first = create(client, project="A")
    second = create(client, project="B")
    assert first["external_id"] == "OPP-000001"
    assert second["external_id"] == "OPP-000002"


def test_a_supplied_crm_or_workbook_id_is_preserved_and_the_sequence_still_advances(client):
    crm = create(client, project="A", external_id="CRM-77")
    minted = create(client, project="B")
    assert crm["external_id"] == "CRM-77"
    # The counter only advances for ids the platform mints.
    assert minted["external_id"] == "OPP-000001"
    dup = client.post("/api/v1/opportunities", json={**PAYLOAD, "project": "C", "external_id": "CRM-77"},
                      headers=headers("director"))
    assert dup.status_code == 409


def test_import_commit_mints_ids_from_the_same_sequence(client):
    import io

    create(client, project="Direct")
    csv = ("Region,Customer,End Customer,Project Name,Part Number,Design Status,Stage,EAU,Disty ASP,"
           "Confidence Level,Owner,Confidence Rationale\n"
           "Korea,SLM,GM,Imported,AX02,Design In,DVT,900,2.5,0.65,jdoe,second source dropped\n")
    dry = client.post("/api/v1/imports/dry-run",
                      files={"file": ("p.csv", io.BytesIO(csv.encode()), "text/csv")},
                      headers=headers("director"))
    assert dry.status_code == 200, dry.text
    commit = client.post(f"/api/v1/imports/{dry.json()['snapshot_id']}/commit",
                         files={"file": ("p.csv", io.BytesIO(csv.encode()), "text/csv")},
                         headers=headers("director"))
    assert commit.status_code in (200, 201), commit.text
    ids = sorted(o["external_id"] for o in client.get("/api/v1/opportunities", headers=headers("director")).json())
    assert ids == ["OPP-000001", "OPP-000002"]
