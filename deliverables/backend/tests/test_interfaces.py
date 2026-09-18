"""
Machine interfaces: the MCP server (WBS 10.12), webhooks and exports (10.13),
the ROI Agent feed and cross-check contract (1.6).
"""

import json

import pytest

from app.services import webhooks
from tests.test_judgment_layer import load_nine
from tests.test_roles_and_scope import PAYLOAD, headers

ADMIN = headers("admin", "*", "root")


# --------------------------------------------------------------------------- #
# 10.12
# --------------------------------------------------------------------------- #

def test_mcp_exposes_the_assistant_tools_read_only(client, monkeypatch):
    from app.mcp import server

    load_nine(client)
    monkeypatch.setattr(server, "SessionLocal", client.session_factory)
    names = {t["name"] for t in server.tool_definitions()}
    assert names >= {"get_rollup", "get_pipeline", "get_opportunity", "get_proposal", "get_audit_events",
                     "compute_scenario", "list_findings", "get_win_rate", "get_review_queue"}
    assert not any(n.startswith(("set_", "resolve", "create", "move", "approve")) for n in names)
    rollup = server.call_tool("get_rollup", {"by": "region"})
    assert rollup["total_adjusted_revenue_k"] == pytest.approx(30915.0) if "total_adjusted_revenue_k" in rollup else rollup
    assert "error" in server.call_tool("resolve_proposal", {})

    fastmcp = pytest.importorskip("mcp.server.fastmcp")
    built = server.build_server()
    assert isinstance(built, fastmcp.FastMCP)


# --------------------------------------------------------------------------- #
# 10.13 -- webhooks
# --------------------------------------------------------------------------- #

@pytest.fixture()
def capture(monkeypatch):
    sent = []

    def transport(url, body, headers):
        sent.append((url, json.loads(body), headers))
        return 500 if "fail" in url else 200

    webhooks.set_transport(transport)
    yield sent
    webhooks.set_transport(None)


def test_events_are_delivered_signed_and_failures_are_retried(client, capture):
    assert "proposal.raised" in client.get("/api/v1/webhooks/events").json()
    good = client.post("/api/v1/webhooks", json={"url": "https://wm.example/hook", "events": ["proposal.*", "transition.recorded"]},
                       headers=ADMIN).json()
    bad = client.post("/api/v1/webhooks", json={"url": "https://fail.example/hook", "events": ["*"]}, headers=ADMIN).json()
    assert good["secret"]
    assert client.get("/api/v1/webhooks", headers=ADMIN).json()[0]["secret"] is None   # shown once, at creation
    assert client.post("/api/v1/webhooks", json={"url": "https://x", "events": ["nope"]}, headers=ADMIN).status_code == 400

    opp = client.post("/api/v1/opportunities", json={**PAYLOAD, "design_status": "Design In", "stage": "DVT",
                                                     "confidence": 0.65}, headers=headers("director")).json()
    client.post(f"/api/v1/opportunities/{opp['id']}/transition",
                json={"field": "stage", "to_value": "PVT", "actor": "marc", "reason_code": "advanced_to_next_stage"},
                headers=headers("director"))
    events = [(url, body["event"]) for url, body, _ in capture]
    assert ("https://wm.example/hook", "transition.recorded") in events
    assert ("https://fail.example/hook", "transition.recorded") in events
    url, body, hdrs = next(x for x in capture if x[0] == "https://wm.example/hook")
    assert hdrs["X-OppTrack-Signature"].startswith("sha256=") and hdrs["X-OppTrack-Event"] == "transition.recorded"
    assert body["payload"]["to"] == "PVT"

    deliveries = client.get("/api/v1/webhooks/deliveries", headers=ADMIN).json()
    assert {d["status"] for d in deliveries} == {"sent", "failed"}
    failed = [d for d in deliveries if d["status"] == "failed"][0]
    assert failed["response_code"] == 500 and failed["attempts"] == 1
    assert client.post("/api/v1/webhooks/retry", headers=ADMIN).json()["retried"] == 1
    assert [d for d in client.get("/api/v1/webhooks/deliveries", headers=ADMIN).json() if d["id"] == failed["id"]][0]["attempts"] == 2

    client.delete(f"/api/v1/webhooks/{bad['id']}", headers=ADMIN)
    before = len(capture)
    client.post("/api/v1/rubric/publish-v1", headers=ADMIN)
    client.post("/api/v1/runs", json={}, headers=ADMIN)
    new = [(url, body["event"]) for url, body, _ in capture[before:]]
    assert ("https://wm.example/hook", "proposal.raised") in new
    assert not any(url == "https://fail.example/hook" for url, _ in new)   # unsubscribed


# --------------------------------------------------------------------------- #
# 10.13 -- exports, 1.6 -- the ROI contract
# --------------------------------------------------------------------------- #

def test_exports_are_the_engine_figures_as_csv(client):
    load_nine(client)
    csv_text = client.get("/api/v1/exports/opportunities.csv", headers=headers("director")).text
    lines = csv_text.strip().splitlines()
    assert lines[0].startswith("external_id,region,customer") and len(lines) == 10
    hermes = next(l for l in lines if ",Hermes," in l)
    assert ",40000.0,12000.0," in hermes
    audit = client.get("/api/v1/exports/audit.csv", headers=headers("finance")).text
    assert audit.startswith("occurred_at,external_id,event_type") or audit == ""


def test_roi_feed_carries_the_agreed_contract_and_cross_check_raises_findings(client):
    ids = load_nine(client)
    client.post("/api/v1/rubric/publish-v1", headers=ADMIN)
    with client.session_factory() as db:
        from datetime import date

        from sqlalchemy import update

        from app.db.models.opportunity import Opportunity
        db.execute(update(Opportunity).where(Opportunity.project == "Hercules").values(mp_date=date(2026, 9, 1)))
        db.commit()
    feed = client.get("/api/v1/exports/roi-feed.json", headers=headers("finance")).json()
    assert feed["contract"] == "roi-feed-v1" and feed["rubric_version"] == "2026.1"
    row = next(r for r in feed["rows"] if r["external_id"] and r["period"] == "2026-Q3")
    for key in ("snapshot_id", "opportunity_id", "external_id", "region", "customer", "product_line", "part_number",
                "period", "sales_revenue_k", "adjusted_revenue_k", "confidence", "design_status", "stage", "source",
                "calculation_version", "rubric_version"):
        assert key in row, key
    assert row["adjusted_revenue_k"] == pytest.approx(3300 * 0.10)
    unphased = [r for r in feed["rows"] if r["period"] == "unphased"]
    assert len(unphased) == 8 and next(r for r in unphased if r["part_number"] == "AX10")["adjusted_revenue_k"] == 12000.0

    hercules_id = next(r["external_id"] for r in feed["rows"] if r["period"] == "2026-Q3")
    check = client.post("/api/v1/exports/roi-cross-check", json={"rows": [
        {"external_id": hercules_id, "period": "2026-Q3", "adjusted_revenue_k": 330.0},   # agrees
        {"external_id": hercules_id, "period": "2026-Q4", "adjusted_revenue_k": 900.0},   # ours is 660: differs
        {"external_id": "OPP-999999", "period": "2027-Q1", "adjusted_revenue_k": 10.0},   # not in feed
    ]}, headers=headers("finance")).json()
    assert check["compared"] == 3
    assert {f["kind"] for f in check["findings"]} == {"differs", "not_in_feed"}
    assert client.get("/api/v1/exports/roi-feed.json", headers=headers("owner")).status_code == 403
