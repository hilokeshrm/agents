"""
API regression test for POST/GET /api/v1/opportunities, backed by an in-memory
SQLite session via a dependency override -- no live Postgres required.
"""

import pytest

PAYLOAD = {
    "region": "Korea", "customer": "SLM", "end_customer": "GM", "project": "Hercules",
    "part_number": "AX01", "design_status": "Design Win", "stage": "PVT",
    "eau_kpcs": 1100, "disty_asp": 3, "confidence": 1.0,
    "owner": "jdoe", "confidence_rationale": "locked design win",
}


def test_create_and_get_opportunity(client):
    created = client.post("/api/v1/opportunities", json=PAYLOAD)
    assert created.status_code == 201
    body = created.json()
    assert body["sales_revenue_k"] == pytest.approx(3300.0)
    assert body["adjusted_revenue_k"] == pytest.approx(3300.0)
    assert body["external_id"].startswith("OPP-")

    fetched = client.get(f"/api/v1/opportunities/{body['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["project"] == "Hercules"


def test_external_id_is_customizable_unique_and_resolves_urls(client):
    created = client.post("/api/v1/opportunities", json={**PAYLOAD, "external_id": "OPP-000001"}).json()
    fetched = client.get("/api/v1/opportunities/OPP-000001")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == created["id"]

    duplicate = client.post("/api/v1/opportunities", json={**PAYLOAD, "external_id": "OPP-000001"})
    assert duplicate.status_code == 409


def test_owner_change_appends_history(client):
    created = client.post("/api/v1/opportunities", json=PAYLOAD).json()
    changed = client.post(
        f"/api/v1/opportunities/{created['external_id']}/owner",
        json={"owner": "manager@example.com", "actor": "jdoe"},
    )
    assert changed.status_code == 201
    assert changed.json()["from_owner"] == "jdoe"
    assert changed.json()["to_owner"] == "manager@example.com"

    history = client.get(f"/api/v1/opportunities/{created['id']}/owner-history")
    assert history.status_code == 200
    assert [(row["from_owner"], row["to_owner"]) for row in history.json()] == [
        (None, "jdoe"), ("jdoe", "manager@example.com")
    ]
    assert client.get(f"/api/v1/opportunities/{created['id']}").json()["owner"] == "manager@example.com"


def test_get_missing_opportunity_404(client):
    resp = client.get("/api/v1/opportunities/does-not-exist")
    assert resp.status_code == 404


def test_create_persists_field_value_provenance_rows(client):
    """WBS 3.6, wired for real: creating an opportunity writes a FieldValue row
    per intake field, cited by ParamSpec id, source=direct_entry, trust=5 (the top of the precedence ladder)."""
    from app.db.models.field_value import TRUST_LEVELS
    from app.db.models.field_value import FieldValue as FieldValueRow
    from app.schemas.opportunity import OpportunityCreate

    created = client.post("/api/v1/opportunities", json=PAYLOAD).json()

    with client.session_factory() as db:
        rows = db.query(FieldValueRow).filter_by(opportunity_id=created["id"]).all()
        by_param = {r.param: r for r in rows}

    # Every field of the full intake schema got a row -- including the ones
    # PAYLOAD leaves at their default (resale_asp, competitor_part, evidence).
    assert len(rows) == len(OpportunityCreate.model_fields)
    assert by_param["V1"].value == "Korea"  # Region
    assert by_param["V1"].source == "direct_entry"
    assert by_param["V1"].trust == TRUST_LEVELS["direct_entry"]
    assert by_param["V9"].value == "PVT"  # Stage
    assert by_param["V26"].value == "jdoe"  # Owner (proposed param, direct-entry only)


def test_create_rejects_unmapped_region_with_findings(client):
    """A region on nobody's list -- canonicalisation must refuse to invent a
    category for it (WBS 3.4), and that refusal must surface as a clean 400,
    not a 500 from a NOT NULL constraint failure downstream."""
    resp = client.post("/api/v1/opportunities", json={**PAYLOAD, "region": "LATAM"})
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail[0]["field"] == "region"
    assert detail[0]["raw_value"] == "LATAM"

    # And nothing was written.
    assert client.get("/api/v1/opportunities").json() == []


def test_create_rejects_forbidden_matrix_a_pairing_after_publication(client):
    from tests.test_api_review import publish

    publish(client)
    resp = client.post("/api/v1/opportunities", json={
        **PAYLOAD, "design_status": "Design Win", "stage": "EVT",
    })
    assert resp.status_code == 400
    assert "cannot be paired" in resp.json()["detail"]


def test_create_canonicalizes_variant_spellings(client):
    """KR -> Korea, D-IN -> Design In, MOBIS -> Mobis -- the same collisions
    proven against the real workbook in test_canonicalize_intake.py, now proven
    through the live API."""
    created = client.post("/api/v1/opportunities", json={
        **PAYLOAD, "region": "KR", "customer": "MOBIS", "design_status": "D-IN",
    }).json()
    assert created["region"] == "Korea"
    assert created["customer"] == "Mobis"
    assert created["design_status"] == "Design In"


def test_list_opportunities(client):
    """Not asserting exact order here: created_at has second-level (SQLite) or
    coarser (observed on this machine) resolution, so two rows created back to
    back can carry an identical timestamp -- ordering between ties is best-effort,
    not a documented guarantee."""
    assert client.get("/api/v1/opportunities").json() == []

    first = client.post("/api/v1/opportunities", json={**PAYLOAD, "project": "Hercules"}).json()
    second = client.post("/api/v1/opportunities", json={**PAYLOAD, "project": "Aphrodite"}).json()

    listed = client.get("/api/v1/opportunities").json()
    assert {o["id"] for o in listed} == {first["id"], second["id"]}
    assert {o["project"] for o in listed} == {"Hercules", "Aphrodite"}


def test_provenance_endpoint_answers_who_put_that_there(client):
    """WBS 3.6 stored the provenance; this is the read that makes it usable --
    one entry per ParamSpec id, cited by name, with its source and trust level."""
    created = client.post("/api/v1/opportunities", json=PAYLOAD).json()
    rows = client.get(f"/api/v1/opportunities/{created['id']}/provenance").json()

    by_param = {r["param"]: r for r in rows}
    assert by_param["V1"]["name"] == "Region"
    assert by_param["V1"]["value"] == "Korea"
    assert by_param["V1"]["source"] == "direct_entry"
    assert by_param["V1"]["trust"] == 5
    assert by_param["V1"]["superseded"] == []
    assert [r["param"] for r in rows] == sorted((r["param"] for r in rows), key=lambda p: int(p[1:]))


def test_lost_at_intake_needs_a_loss_reason_and_carries_zero_confidence(client):
    # Matrix A: Lost is terminal, 0.00 at every stage, and needs a loss reason --
    # the transition path enforces that; intake must not be the way round it.
    lost = {**PAYLOAD, "project": "Dead socket", "design_status": "Lost", "stage": "EVT"}
    no_reason = client.post("/api/v1/opportunities", json={**lost, "confidence": 0})
    assert no_reason.status_code == 400
    assert "loss_reason" in no_reason.json()["detail"]

    bad_code = client.post("/api/v1/opportunities", json={**lost, "confidence": 0, "loss_reason": "vibes"})
    assert bad_code.status_code == 400
    assert "vocabulary" in bad_code.json()["detail"]

    weighted = client.post("/api/v1/opportunities", json={**lost, "confidence": 0.5, "loss_reason": "price"})
    assert weighted.status_code == 400
    assert "0.00" in weighted.json()["detail"]

    ok = client.post("/api/v1/opportunities", json={**lost, "confidence": 0, "loss_reason": "price"})
    assert ok.status_code == 201
    assert ok.json()["adjusted_revenue_k"] == 0
    # The loss reason is on the seed event, not lost in the request.
    history = client.get(f"/api/v1/opportunities/{ok.json()['id']}/state-history").json()
    seeds = [e for e in history if e["field"] == "design_status"]
    assert seeds and seeds[0]["reason_code"] == "price"


def test_region_scoped_manager_cannot_create_outside_scope(client):
    korea = {"X-OppTrack-Role": "manager", "X-OppTrack-Actor": "kim", "X-OppTrack-Regions": "Korea"}
    out = client.post("/api/v1/opportunities", json={**PAYLOAD, "region": "Europe"}, headers=korea)
    assert out.status_code == 403 and "scoped to" in out.json()["detail"]
    assert client.post("/api/v1/opportunities", json={**PAYLOAD, "region": "Korea"}, headers=korea).status_code == 201
