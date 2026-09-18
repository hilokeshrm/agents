"""API regression tests for contacts (WBS-adjacent, added for the UI build)."""


def test_contacts_list_starts_empty(client):
    """Nothing seeded -- the real workbook has no person-level fields."""
    assert client.get("/api/v1/contacts").json() == []


def test_create_list_delete_contact(client):
    created = client.post("/api/v1/contacts", json={
        "name": "Jane Kim", "title": "Lamp EE Manager", "account": "Mobis",
        "email": "jane.kim@example.com", "phone": "+82-10-0000-0000",
    })
    assert created.status_code == 201
    body = created.json()
    assert body["name"] == "Jane Kim"

    listed = client.get("/api/v1/contacts").json()
    assert len(listed) == 1

    deleted = client.delete(f"/api/v1/contacts/{body['id']}")
    assert deleted.status_code == 204
    assert client.get("/api/v1/contacts").json() == []


def test_delete_missing_contact_404(client):
    resp = client.delete("/api/v1/contacts/does-not-exist")
    assert resp.status_code == 404
