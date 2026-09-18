"""API regression tests for the dev tools (local debugging aid, not a WBS task)."""


def test_list_tables_includes_every_real_table(client):
    tables = client.get("/api/v1/dev/tables").json()
    names = {t["name"] for t in tables}
    # The fourteen real tables (WBS 9.1's ten, plus contact, run, owner history,
    # and the OPP-000001 counter from WBS 2.4 -- see app/db/models/__init__.py).
    assert names == {
        "opportunity", "state_history", "snapshot", "field_value", "forecast",
        "proposal", "confidence_event", "finding", "rubric_version", "calibration",
        "contact", "run", "owner_history", "opportunity_sequence",
        "target", "actual", "notification", "app_user", "memory_chunk", "market_programme", "webhook_subscription", "webhook_delivery", "conversation", "auth_account", "auth_session",
    }
    assert all(isinstance(t["row_count"], int) for t in tables)


def test_get_table_returns_columns_and_rows(client):
    client.post("/api/v1/opportunities", json={
        "region": "Korea", "customer": "SLM", "end_customer": "GM", "project": "Hercules",
        "part_number": "AX01", "design_status": "Design Win", "stage": "PVT",
        "eau_kpcs": 1100, "disty_asp": 3, "confidence": 1.0,
        "owner": "jdoe", "confidence_rationale": "locked",
    })
    body = client.get("/api/v1/dev/tables/opportunity").json()
    assert "id" in body["columns"]
    assert "project" in body["columns"]
    assert len(body["rows"]) == 1
    project_idx = body["columns"].index("project")
    assert body["rows"][0][project_idx] == "Hercules"


def test_get_table_unknown_name_404(client):
    assert client.get("/api/v1/dev/tables/does_not_exist").status_code == 404


def test_get_log_unknown_source_404(client):
    assert client.get("/api/v1/dev/logs/bogus").status_code == 404


def test_get_log_missing_file_returns_empty_not_error(client):
    resp = client.get("/api/v1/dev/logs/backend")
    assert resp.status_code == 200
    assert "lines" in resp.json()


def test_list_logs_includes_known_sources(client):
    sources = {row["source"] for row in client.get("/api/v1/dev/logs").json()}
    assert {"backend", "frontend"} <= sources


def test_status_reports_db_and_config(client):
    body = client.get("/api/v1/dev/status").json()
    assert body["db"]["dialect"] == "sqlite"
    assert body["db"]["table_count"] > 0
    assert body["config"]["auth_mode"] in {"headers", "local"}
    assert body["uptime_seconds"] >= 0
    assert "logs" in body
