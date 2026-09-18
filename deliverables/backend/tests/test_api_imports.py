"""
Import wizard: dry run, then commit (WBS 4.6, 10.11).

The CSV below is written to exercise the three things the wizard exists to catch
before anything is written: a row that will not canonicalise ("LATAM" is on
nobody's region list), a row missing a field revenue cannot be
computed without, and a value that will not coerce (the workbook's own TBD).
"""

import io

from tests.test_roles_and_scope import headers

CSV = """Region,Customer,End Customer,Project Name,Part Number,Design Status,Stage,EAU,Disty ASP,Confidence Level,Owner,Confidence Rationale,M/P Date,Competitor Part#
Korea,MOBIS,GM,Hercules,AX01,Design Win,PVT,1100,3,1.0,jdoe,locked design win,Dec'26,RIVAL-1
KR,Mobis,GM,Aphrodite,AX02,D-IN,DVT,900,2.5,0.8,jdoe,second source dropped,June'27,
LATAM,ODE,VW,Dresden,AX03,Evaluation,EVT,500,4,0.5,priya,early evaluation,Sep'27,
Europe,,,Skeleton,AX04,Design Win,PVT,TBD,,,,,,
"""


def upload(client, text=CSV, filename="pipeline.csv"):
    return client.post(
        "/api/v1/imports/dry-run",
        files={"file": (filename, io.BytesIO(text.encode()), "text/csv")},
        headers=headers("owner", "*", "jdoe"),
    )


def test_dry_run_maps_headers_and_reports_what_would_fail(client):
    body = upload(client).json()

    assert body["row_count"] == 4
    assert body["mapping"]["Confidence Level"] == "confidence"
    assert body["mapping"]["M/P Date"] == "mp_date"
    assert body["unmapped_headers"] == []

    # Rows 1 and 2 pass; row 3's region does not canonicalise; row 4 is a
    # skeleton row of the kind ProjectTrack rows 14-18 actually are -- a design
    # win with a region, a status and an EAU, and no customer, ASP or confidence.
    assert body["would_create"] == 2
    assert body["would_block"] == 2

    rows = {r["index"]: r for r in body["rows"]}
    assert rows[2]["values"]["region"] == "Korea"           # KR canonicalised
    assert rows[2]["values"]["design_status"] == "Design In"  # D-IN canonicalised
    assert rows[1]["values"]["mp_date"] == "2026-12-01"     # Dec'26 coerced

    canon = [f for f in rows[3]["findings"] if f["rule_id"] == "CANON"]
    assert canon and "not invented" in canon[0]["message"]

    required = {f["field"] for f in rows[4]["findings"] if f["rule_id"] == "REQUIRED"}
    assert {"customer", "disty_asp", "confidence"} <= required
    coerce = [f for f in rows[4]["findings"] if f["rule_id"] == "COERCE"]
    assert any("not a number -- null, not zero" in f["message"] for f in coerce)


def test_dry_run_writes_nothing_but_the_snapshot_and_its_findings(client):
    before = client.get("/api/v1/opportunities").json()
    body = upload(client).json()
    after = client.get("/api/v1/opportunities").json()

    assert before == after
    assert body["findings_stored"] > 0
    snapshots = client.get("/api/v1/imports").json()
    assert snapshots[0]["id"] == body["snapshot_id"]
    assert snapshots[0]["sealed_at"] is not None
    assert snapshots[0]["blocking_count"] >= 2

    findings = client.get(f"/api/v1/imports/{body['snapshot_id']}/findings").json()
    assert any(f["message"].startswith("row 3") for f in findings)


def test_commit_creates_only_the_rows_that_passed(client):
    dry = upload(client).json()
    result = client.post(f"/api/v1/imports/{dry['snapshot_id']}/commit",
                         headers=headers("owner", "*", "jdoe")).json()

    assert result["created"] == 2
    assert result["blocked"] == 2

    projects = {o["project"] for o in client.get("/api/v1/opportunities").json()}
    assert projects == {"Hercules", "Aphrodite"}
    assert "Dresden" not in projects and "Skeleton" not in projects


def test_imported_values_carry_the_lowest_trust_level(client):
    """Import is migration and backfill, below every connector and far below a
    human edit -- the connector precedence order as data, not convention."""
    from app.db.models.field_value import TRUST_LEVELS
    from app.db.models.field_value import FieldValue as FieldValueRow

    dry = upload(client).json()
    result = client.post(f"/api/v1/imports/{dry['snapshot_id']}/commit",
                         headers=headers("owner", "*", "jdoe")).json()

    with client.session_factory() as db:
        rows = db.query(FieldValueRow).filter_by(opportunity_id=result["opportunity_ids"][0]).all()

    assert rows
    assert {r.source for r in rows} == {"import"}
    assert {r.trust for r in rows} == {TRUST_LEVELS["import"]}
    assert TRUST_LEVELS["import"] < TRUST_LEVELS["crm"] < TRUST_LEVELS["direct_entry"]


def test_commit_revalidates_the_sealed_bytes_not_a_second_upload(client):
    """The commit takes a snapshot id, so what gets written is what was
    approved. A snapshot that does not exist is a 404, not an empty success."""
    assert client.post("/api/v1/imports/nope/commit", headers=headers("owner")).status_code == 404


def test_dry_run_blocks_forbidden_matrix_a_pairing_after_publication(client):
    from tests.test_api_review import publish

    publish(client)
    body = upload(client, CSV.replace("Design Win,PVT", "Design Win,EVT")).json()
    rows = {r["index"]: r for r in body["rows"]}
    matrix_findings = [f for f in rows[1]["findings"] if f["rule_id"] == "MATRIX_A"]
    assert matrix_findings
    assert rows[1]["blocking"] is True
    assert body["would_block"] == 3


def test_dry_run_blocks_existing_business_identity_as_duplicate(client):
    existing = client.post("/api/v1/opportunities", json={
        "region": "Korea", "customer": "Mobis", "end_customer": "GM", "project": "Hercules",
        "part_number": "AX01", "design_status": "Design Win", "stage": "PVT",
        "eau_kpcs": 1100, "disty_asp": 3, "confidence": 1.0,
        "owner": "jdoe", "confidence_rationale": "existing",
    }).json()
    text = "Region,Customer,End Customer,Project Name,Part Number,Design Status,Stage,EAU,Disty ASP,Confidence Level,Owner,Confidence Rationale\nKorea,MOBIS,GM,Hercules,AX01,Design Win,PVT,1100,3,1.0,jdoe,reimport\n"
    body = upload(client, text).json()
    row = body["rows"][0]
    duplicate = [f for f in row["findings"] if f["rule_id"] == "DUPLICATE"]
    assert duplicate
    assert existing["external_id"] in duplicate[0]["message"]
    assert row["blocking"] is True
    assert body["would_create"] == 0


def test_dry_run_blocks_duplicate_rows_inside_one_upload(client):
    text = "Region,Customer,End Customer,Project Name,Part Number,Design Status,Stage,EAU,Disty ASP,Confidence Level,Owner,Confidence Rationale\nKorea,MOBIS,GM,Hercules,AX01,Design Win,PVT,1100,3,1.0,jdoe,first\nKorea,MOBIS,GM,Hercules,AX01,Design Win,PVT,1100,3,1.0,jdoe,second\n"
    body = upload(client, text).json()
    assert [f for f in body["rows"][1]["findings"] if f["rule_id"] == "DUPLICATE"]
    assert body["would_create"] == 1
    assert body["would_block"] == 1


def test_a_file_with_no_recognisable_column_is_refused(client):
    resp = upload(client, "alpha,beta\n1,2\n")
    assert resp.status_code == 400
    assert "map them by hand" in resp.json()["detail"]


def test_finance_cannot_import(client):
    assert upload_as(client, "finance").status_code == 403


def upload_as(client, role):
    return client.post(
        "/api/v1/imports/dry-run",
        files={"file": ("pipeline.csv", io.BytesIO(CSV.encode()), "text/csv")},
        headers=headers(role),
    )
