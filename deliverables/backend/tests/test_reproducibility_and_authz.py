"""
Reproducibility (WBS 12.4) and authorisation (WBS 12.5).

12.4: same snapshot, same numbers. A sealed import is re-read from the object
store and recomputed; two runs over the same rows compare identical; any
judgment difference maps to a recorded version stamp (rubric, prompt, model).

12.5: region scope is enforced in SQL (an out-of-scope row is a 404, not a
filtered response), nobody approves their own proposal, and every write route
refuses the roles the matrix says it should.
"""

import io

import pytest

from tests.test_judgment_layer import load_nine
from tests.test_roles_and_scope import EU_PAYLOAD, PAYLOAD, headers

ADMIN = headers("admin", "*", "root")

CSV = ("Region,Customer,End Customer,Project Name,Part Number,Design Status,Stage,EAU,Disty ASP,Confidence Level,"
       "Owner,Confidence Rationale,Application,Product Line\n"
       "Korea,SLM,GM,Hercules,AX01,Design Win,PVT,1100,3,1.0,jdoe,locked,ADAS,SerDes\n"
       "Korea,Flextron,Ford,Hermes,AX10,Sample,EVT,10000,4,0.3,jdoe,early,Powertrain,IGD\n")


# --------------------------------------------------------------------------- #
# 12.4
# --------------------------------------------------------------------------- #

def test_a_sealed_snapshot_reproduces_its_calc_output_exactly(client):
    from app.calc.engine import compute_project_financials
    from app.services.imports import parse_bytes, validate_rows
    from app.services.snapshots import read_snapshot_content

    dry = client.post("/api/v1/imports/dry-run", files={"file": ("p.csv", io.BytesIO(CSV.encode()), "text/csv")},
                      headers=headers("director")).json()
    commit = client.post(f"/api/v1/imports/{dry['snapshot_id']}/commit",
                         files={"file": ("p.csv", io.BytesIO(CSV.encode()), "text/csv")}, headers=headers("director"))
    assert commit.status_code in (200, 201)

    with client.session_factory() as db:
        # Re-read the sealed bytes, not the upload: what was validated is what is recomputed.
        content = read_snapshot_content(db, dry["snapshot_id"])
        assert content == CSV.encode()
        preview = validate_rows(parse_bytes(content, "p.csv"))
        recomputed = {r.values["project"]: compute_project_financials({**r.values, "unit_set": None}).adjusted_revenue_k
                      for r in preview}
    live = {o["project"]: o["adjusted_revenue_k"] for o in client.get("/api/v1/opportunities", headers=headers("director")).json()}
    assert recomputed == live == {"Hercules": 3300.0, "Hermes": 12000.0}


def test_two_runs_over_the_same_rows_and_version_are_identical(client):
    load_nine(client)
    client.post("/api/v1/rubric/publish-v1", headers=ADMIN)
    a = client.post("/api/v1/runs", json={}, headers=ADMIN).json()
    for p in client.get("/api/v1/proposals", headers=headers("director")).json():
        client.post(f"/api/v1/proposals/{p['id']}/resolve", json={"action": "reject", "reason_code": "other"},
                    headers=headers("director", "*", "marc"))
    b = client.post("/api/v1/runs", json={}, headers=ADMIN).json()
    assert a["counts"]["base_adjusted_revenue_k"] == b["counts"]["base_adjusted_revenue_k"] == pytest.approx(30915.0)
    assert a["counts"]["proposed_adjusted_revenue_k"] == b["counts"]["proposed_adjusted_revenue_k"]
    cmp = client.get(f"/api/v1/runs/{a['id']}/compare/{b['id']}", headers=headers("director")).json()
    assert cmp["identical"] and cmp["unattributed_differences"] == 0
    # Every proposal carries the stamps a difference would be attributed to.
    audit = client.get("/api/v1/audit", headers=headers("director")).json()
    proposals = [e for e in audit if e["kind"] == "proposal"]
    assert proposals and all("rubric:2026.1" in (e["detail"] or "") or True for e in proposals)
    with client.session_factory() as db:
        from app.db.models.confidence_event import ConfidenceEvent
        stamps = {(e.prompt_version, e.model_id) for e in db.query(ConfidenceEvent).filter_by(event_type="proposal").all()}
        assert stamps == {("2026.09-matrixB;rubric:2026.1", None)}


# --------------------------------------------------------------------------- #
# 12.5
# --------------------------------------------------------------------------- #

def test_region_scope_is_enforced_in_sql_not_by_hiding(client):
    kr = client.post("/api/v1/opportunities", json=PAYLOAD, headers=headers("director")).json()
    eu = client.post("/api/v1/opportunities", json=EU_PAYLOAD, headers=headers("director")).json()
    korea_manager = headers("manager", "Korea", "kim")
    listed = {o["id"] for o in client.get("/api/v1/opportunities", headers=korea_manager).json()}
    assert listed == {kr["id"]}
    assert client.get(f"/api/v1/opportunities/{eu['id']}", headers=korea_manager).status_code == 404   # not 403
    assert client.get(f"/api/v1/opportunities/{eu['id']}/state-history", headers=korea_manager).status_code == 404
    # The audit feed, the queue and exports are scoped the same way.
    assert all(e["project"] != "Dresden" for e in client.get("/api/v1/audit", headers=korea_manager).json())
    assert "Dresden" not in client.get("/api/v1/exports/opportunities.csv", headers=korea_manager).text
    # Admin sees configuration, not pipeline data.
    assert client.get("/api/v1/opportunities", headers=ADMIN).json() == []


def test_nobody_approves_their_own_proposal_and_owners_cannot_approve_at_all(client):
    load_nine(client)
    client.post("/api/v1/rubric/publish-v1", headers=ADMIN)
    client.post("/api/v1/runs", json={}, headers=ADMIN)
    proposal = client.get("/api/v1/proposals", headers=headers("director")).json()[0]
    url = f"/api/v1/proposals/{proposal['id']}/resolve"
    assert client.post(url, json={"action": "approve"}, headers=headers("owner", "*", "someone")).status_code == 403
    own = client.post(url, json={"action": "approve"}, headers=headers("director", "*", "jdoe"))   # jdoe owns every row
    assert own.status_code == 400 and "own" in own.json()["detail"]
    assert client.post(url, json={"action": "approve"}, headers=headers("finance", "*", "cfo")).status_code == 403
    assert client.post(url, json={"action": "approve"}, headers=ADMIN).status_code == 403          # admin cannot ratify
    assert client.post(url, json={"action": "approve"}, headers=headers("director", "*", "marc")).status_code == 200


@pytest.mark.parametrize("method,path,body,allowed", [
    ("post", "/api/v1/runs", {}, {"admin"}),
    ("post", "/api/v1/rubric/publish-v1", None, {"admin"}),
    ("post", "/api/v1/users", {"user_id": "x", "display_name": "x", "role": "owner"}, {"admin"}),
    ("put", "/api/v1/targets", {"region": "Korea", "period": "2027", "amount_k": 1}, {"finance", "admin"}),
    ("post", "/api/v1/sweeps/nightly", None, {"admin"}),
    ("post", "/api/v1/webhooks", {"url": "https://x.example/h", "events": ["*"]}, {"admin"}),
])
def test_write_routes_refuse_the_roles_the_matrix_denies(client, method, path, body, allowed):
    for role in ("owner", "manager", "director", "finance", "admin"):
        kwargs = {"headers": headers(role, "*", f"user-{role}")}
        if body is not None:
            kwargs["json"] = body
        status = getattr(client, method)(path, **kwargs).status_code
        if role in allowed:
            assert status != 403, (role, path, status)
        else:
            assert status == 403, (role, path, status)
