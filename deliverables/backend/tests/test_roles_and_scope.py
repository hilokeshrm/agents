"""
Roles, the permission matrix and region scope (WBS 9.5, app/security/roles.py).

The three cells the product document says carry the whole separation of duties
get their own assertions, because a transcription error in that table is exactly
the kind of bug that looks like a working screen.
"""

import pytest

from app.security.roles import Actor, PERMISSIONS, ROLES

PAYLOAD = {
    "region": "Korea", "customer": "SLM", "end_customer": "GM", "project": "Hercules",
    "part_number": "AX01", "design_status": "Design Win", "stage": "PVT",
    "eau_kpcs": 1100, "disty_asp": 3, "confidence": 1.0,
    "owner": "jdoe", "confidence_rationale": "locked design win",
}
EU_PAYLOAD = {**PAYLOAD, "region": "Europe", "project": "Dresden", "customer": "ODE", "confidence": 0.5}


def headers(role: str, regions: str = "*", actor: str = "tester") -> dict:
    return {"X-OppTrack-Role": role, "X-OppTrack-Regions": regions, "X-OppTrack-Actor": actor}


def test_matrix_covers_every_role():
    for action, grants in PERMISSIONS.items():
        assert set(grants) == set(ROLES), f"{action} does not name every role"


def test_the_three_separation_of_duties_cells():
    """An owner cannot approve, a manager cannot edit the rubric that judges
    them, and an admin who edits the rubric cannot ratify what it produces."""
    assert PERMISSIONS["approve_reject_proposal"]["owner"] == "no"
    assert PERMISSIONS["publish_rubric"]["manager"] == "no"
    assert PERMISSIONS["approve_reject_proposal"]["admin"] == "no"


def test_nobody_can_edit_an_audit_entry():
    assert set(PERMISSIONS["edit_audit_entry"].values()) == {"no"}


def test_own_region_grant_is_scoped_not_global():
    manager = Actor(user_id="priya", role="manager", regions=("Europe",))
    assert manager.can_act_on_region("approve_reject_proposal", "Europe")
    assert not manager.can_act_on_region("approve_reject_proposal", "Korea")

    director = Actor(user_id="marc", role="director", regions=())
    assert director.can_act_on_region("approve_reject_proposal", "Korea")


def test_admin_sees_no_pipeline_data_by_default():
    admin = Actor(user_id="root", role="admin", regions=())
    assert not admin.can("view_own_region")
    assert not admin.can("view_all_regions")


def test_region_scope_is_applied_to_the_query(client):
    client.post("/api/v1/opportunities", json=PAYLOAD, headers=headers("director"))
    client.post("/api/v1/opportunities", json=EU_PAYLOAD, headers=headers("director"))

    korea_only = client.get("/api/v1/opportunities", headers=headers("owner", "Korea")).json()
    assert [o["project"] for o in korea_only] == ["Hercules"]

    everything = client.get("/api/v1/opportunities", headers=headers("director")).json()
    assert {o["project"] for o in everything} == {"Hercules", "Dresden"}


def test_out_of_scope_row_is_404_not_403(client):
    """A 403 would confirm the row exists, which is itself a disclosure."""
    created = client.post("/api/v1/opportunities", json=EU_PAYLOAD, headers=headers("director")).json()
    resp = client.get(f"/api/v1/opportunities/{created['id']}", headers=headers("owner", "Korea"))
    assert resp.status_code == 404


def test_admin_sees_no_rows_at_all(client):
    client.post("/api/v1/opportunities", json=PAYLOAD, headers=headers("director"))
    assert client.get("/api/v1/opportunities", headers=headers("admin")).json() == []


@pytest.mark.parametrize("role", ["finance", "admin", "service"])
def test_roles_without_a_create_grant_are_refused_at_the_route(client, role):
    resp = client.post("/api/v1/opportunities", json=PAYLOAD, headers=headers(role))
    assert resp.status_code == 403
    assert "may not" in resp.json()["detail"]


def test_unknown_role_is_rejected(client):
    assert client.get("/api/v1/opportunities", headers=headers("wizard")).status_code == 400


def test_access_matrix_and_me_are_served_from_one_copy(client):
    matrix = client.get("/api/v1/access/matrix").json()
    assert len(matrix["rows"]) == len(PERMISSIONS)
    assert matrix["roles"] == list(ROLES)

    me = client.get("/api/v1/access/me", headers=headers("manager", "Europe", "priya")).json()
    assert me["role"] == "manager"
    assert me["regions"] == ["Europe"]
    assert me["grants"]["approve_reject_proposal"] == "own_region"
    assert "header" in me["identity_source"]
