"""
Connectors (WBS 11.1-11.6): the framework, the precedence ladder and the
reconciliation queue, and the four connectors over file drops.
"""

import io

import pytest

from tests.test_roles_and_scope import PAYLOAD, headers

ADMIN = headers("admin", "*", "root")


def upload(client, name, text, *, dry_run=False, filename="drop.csv", hdrs=ADMIN):
    return client.post(f"/api/v1/connectors/{name}/pull",
                       files={"file": (filename, io.BytesIO(text.encode()), "text/csv")},
                       data={"dry_run": "true" if dry_run else "false"}, headers=hdrs)


def test_catalogue_declares_supplies_trust_and_cadence(client):
    cat = {c["name"]: c for c in client.get("/api/v1/connectors").json()}
    assert set(cat) == {"crm", "erp", "disty_pos", "market_data"}
    assert cat["erp"]["trust"] > cat["crm"]["trust"] > cat["disty_pos"]["trust"]      # decision #63
    assert "A1" in cat["erp"]["supplies"] and "A2" in cat["disty_pos"]["supplies"]
    assert cat["crm"]["cadence"] == "nightly"


def test_crm_pull_applies_higher_trust_dimensions_and_queues_the_rest(client):
    opp = client.post("/api/v1/opportunities", json={**PAYLOAD, "external_id": "CRM-1", "design_status": "Design In",
                                                     "stage": "DVT", "confidence": 0.65}, headers=headers("director")).json()
    # Seed an imported (lowest-trust) provenance for the end customer so CRM out-ranks it.
    with client.session_factory() as db:
        from app.db.models.field_value import FieldValue
        for fv in db.query(FieldValue).filter_by(opportunity_id=opp["id"]).all():
            if fv.param == "V3":
                db.execute(FieldValue.__table__.update().where(FieldValue.id == fv.id).values(trust=1, source="import"))
        db.commit()
    csv = ("Opportunity ID,Region,Customer,Project Name,Part Number,End Customer,Design Status,Stage,M/P Date\n"
           "CRM-1,Korea,SLM,Hercules,AX01,General Motors,Design Win,PVT,Mar'27\n")
    dry = upload(client, "crm", csv, dry_run=True).json()
    assert dry["dry_run"] is True and dry["matched"] == 4 and dry["applied"] == 2 and dry["reconciliation_items"] == 2
    assert client.get(f"/api/v1/opportunities/{opp['id']}").json()["end_customer"] == "GM"   # nothing written

    upload(client, "crm", csv).json()
    after = client.get(f"/api/v1/opportunities/{opp['id']}").json()
    assert after["end_customer"] == "General Motors"              # CRM (3) out-ranked import (1): applied
    assert after["mp_date"] == "2027-03-01"                        # no prior provenance beats CRM
    assert after["design_status"] == "Design In" and after["stage"] == "DVT"   # gated: never written
    queue = client.get("/api/v1/connectors/reconciliation", headers=headers("director")).json()
    assert {q["field"] for q in queue} == {"design_status", "stage"}
    assert all(q["gated"] for q in queue)
    # Re-pulling the same file queues nothing twice.
    upload(client, "crm", csv)
    assert len(client.get("/api/v1/connectors/reconciliation", headers=headers("director")).json()) == 2


def test_a_human_edit_is_never_overwritten_by_a_connector(client):
    client.post("/api/v1/opportunities", json={**PAYLOAD, "external_id": "CRM-2"}, headers=headers("director")).json()
    csv = "Opportunity ID,End Customer\nCRM-2,Somebody Else\n"
    result = upload(client, "crm", csv).json()
    assert result["applied"] == 0 and result["reconciliation_items"] == 1
    item = client.get("/api/v1/connectors/reconciliation", headers=headers("director")).json()[0]
    assert item["current_trust"] == 5 and item["trust"] == 3
    # A director takes the connector's value: it lands at the top of the ladder.
    ok = client.post(f"/api/v1/proposals/{item['id']}/resolve", json={"action": "approve"},
                     headers=headers("director", "*", "marc"))
    assert ok.status_code == 200
    assert client.get(f"/api/v1/opportunities/{item['opportunity_id']}").json()["end_customer"] == "Somebody Else"


def test_taking_a_lost_status_from_the_crm_needs_the_close_grant_and_a_reason(client):
    client.post("/api/v1/opportunities", json={**PAYLOAD, "external_id": "CRM-3", "design_status": "Design In",
                                               "stage": "DVT", "confidence": 0.65}, headers=headers("director"))
    upload(client, "crm", "Opportunity ID,Design Status\nCRM-3,Lost\n")
    item = client.get("/api/v1/connectors/reconciliation", headers=headers("director")).json()[0]
    url = f"/api/v1/proposals/{item['id']}/resolve"
    assert client.post(url, json={"action": "approve"}, headers=headers("owner", "*", "kim")).status_code == 403
    no_reason = client.post(url, json={"action": "approve"}, headers=headers("director", "*", "marc"))
    assert no_reason.status_code == 400 and "loss_reason" in no_reason.json()["detail"]
    ok = client.post(url, json={"action": "approve", "reason_code": "competitor"}, headers=headers("director", "*", "marc"))
    assert ok.status_code == 200
    assert client.get(f"/api/v1/opportunities/{item['opportunity_id']}").json()["design_status"] == "Lost"


def test_erp_and_pos_load_actuals_and_erp_prices_reconcile(client):
    client.post("/api/v1/opportunities", json=PAYLOAD, headers=headers("director"))
    erp = ("part_number,customer,region,year,quarter,revenue_k,units_kpcs,invoiced_asp\n"
           "AX01,SLM,Korea,2026,3,300,100,3.05\n")
    result = upload(client, "erp", erp).json()
    assert result["actuals_loaded"] == 1 and result["reconciliation_items"] == 1   # $3.05 vs the human-entered $3.00
    pos = "part_number,customer,region,year,quarter,units_kpcs\nAX01,SLM,Korea,2026,3,95\n"
    assert upload(client, "disty_pos", pos).json()["actuals_loaded"] == 1
    actuals = client.get("/api/v1/actuals", headers=headers("finance")).json()
    assert {(a["source"], a["units_kpcs"]) for a in actuals} == {("erp", 100.0), ("pos", 95.0)}
    body = client.get("/api/v1/analyses", headers=headers("director")).json()
    assert "A1" in body["available_parameters"]


def test_market_data_lights_up_the_eau_cross_check_and_white_space(client):
    client.post("/api/v1/opportunities", json={**PAYLOAD, "end_customer": "Ford", "application": "Powertrain",
                                               "eau_kpcs": 10000, "unit_set": 15}, headers=headers("director"))
    body = client.get("/api/v1/analyses", headers=headers("director")).json()
    assert {a["key"]: a["missing"] for a in body["dark"]}["eau_cross_check"] == ["P1", "P2"]
    feed = ("programme,oem,region,application,sop,build_volume_ksets\n"
            "F-150 Lightning,Ford,US,Powertrain,Jun'28,400\n"
            "Ioniq 7,Hyundai/Kia,Korea,Lighting,Mar'28,600\n")
    assert upload(client, "market_data", feed).json()["programmes_loaded"] == 2
    ran = {a["key"]: a for a in client.get("/api/v1/analyses", headers=headers("director")).json()["ran"]}
    xc = ran["eau_cross_check"]
    check = next(r for r in xc["rows"] if r.get("project") == "Hercules")
    assert check["implied_ksets"] == pytest.approx(666.67, abs=0.01) and check["implausible"] is True   # 667 vs 400
    assert [r["programme"] for r in xc["rows"] if r.get("kind") == "white_space"] == ["Ioniq 7"]


def test_only_a_service_account_or_admin_may_pull(client):
    assert upload(client, "crm", "Opportunity ID\nX\n", hdrs=headers("director")).status_code == 403
    assert upload(client, "nope", "x\n").status_code == 404
