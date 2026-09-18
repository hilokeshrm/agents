"""
The review loop end to end (WBS 10.5, 10.7, 10.9): publish a rubric version,
trigger a run, read the queue, resolve a proposal three ways.

Runs against the MOCK scorer, which is what settings.judgment_mode defaults to
-- these tests are about the machinery around the model call (versioning, guards,
band rule, separation of duties, audit), not about what a model says.
"""

import pytest

from tests.test_roles_and_scope import EU_PAYLOAD, PAYLOAD, headers

DRAFT_FACTORS = {
    "factors": [
        {"key": k, "label": k, "guidance": "", "enabled": True}
        for k in ("stage_status_mismatch", "named_competitor_threat", "design_win_lock_in",
                  "early_stage_optimism", "customer_concentration", "submitter_calibration")
    ],
    "caps": {"factor_cap_pp": 10.0, "confidence_ceiling": None, "confidence_floor": None},
}


def publish(client, label="2026.1", matrix_a=None, factors=None):
    body = {
        "label": label,
        "matrix_a": matrix_a if matrix_a is not None else client.get("/api/v1/rubric/draft").json()["matrix_a"],
        "rubric_factors": factors or DRAFT_FACTORS,
    }
    resp = client.post("/api/v1/rubric/versions", json=body, headers=headers("admin"))
    assert resp.status_code == 201, resp.text
    return resp.json()


def seed(client):
    # A valid Matrix A pairing (Design Win at PVT) with a named competitor, so
    # J-02 fires and J-03 supports; the entered 1.00 sits above the 0.95
    # ceiling, so the proposal is also clamped and flagged.
    korea = client.post("/api/v1/opportunities",
                        json={**PAYLOAD, "competitor_part": "RIVAL-1"},
                        headers=headers("director")).json()
    europe = client.post("/api/v1/opportunities", json=EU_PAYLOAD, headers=headers("director")).json()
    return korea, europe


# --------------------------------------------------------------------------- #
# Rubric versions
# --------------------------------------------------------------------------- #

def test_draft_grid_starts_with_recommended_matrix_a_defaults(client):
    """The draft opens with the recommended v1 policy, including forbidden cells."""
    draft = client.get("/api/v1/rubric/draft").json()
    cells = draft["matrix_a"]["cells"]
    assert cells, "the grid should list every canonical pairing"
    assert cells["Promotion|Concept"] == {"baseline": 0.1, "allowed": True}
    assert cells["Design Win|PVT"] == {"baseline": 0.9, "allowed": True}
    assert cells["Design Win|EVT"] == {"baseline": None, "allowed": False}
    assert cells["Lost|Concept"] == {"baseline": 0.0, "allowed": True}
    assert draft["based_on_version_id"] is None


def test_only_an_admin_can_publish(client):
    body = {"label": "x", "matrix_a": {}, "rubric_factors": DRAFT_FACTORS}
    assert client.post("/api/v1/rubric/versions", json=body, headers=headers("manager")).status_code == 403
    assert client.post("/api/v1/rubric/versions", json=body, headers=headers("director")).status_code == 403
    assert client.post("/api/v1/rubric/versions", json=body, headers=headers("admin")).status_code == 201


def test_labels_are_unique_because_a_proposal_cites_them(client):
    publish(client, "2026.1")
    body = {"label": "2026.1", "matrix_a": {}, "rubric_factors": DRAFT_FACTORS}
    assert client.post("/api/v1/rubric/versions", json=body, headers=headers("admin")).status_code == 409


def test_impact_preview_is_deterministic_and_writes_nothing(client):
    korea, _ = seed(client)
    matrix = client.get("/api/v1/rubric/draft").json()["matrix_a"]
    matrix["cells"]["Design Win|PVT"] = {"baseline": 0.35, "allowed": True}

    impact = client.post("/api/v1/rubric/impact",
                         json={"label": "draft", "matrix_a": matrix, "rubric_factors": DRAFT_FACTORS}).json()
    row = next(r for r in impact["rows"] if r["opportunity_id"] == korea["id"])
    assert row["baseline"] == 0.35
    assert row["delta_pp"] == pytest.approx(65.0)  # entered 1.00 against a 0.35 baseline
    assert impact["rows_off_baseline"] == 2
    # The recommended draft covers every canonical pairing.
    assert impact["rows_unset_cell"] == 0
    assert client.get("/api/v1/rubric/versions").json() == []


# --------------------------------------------------------------------------- #
# Runs
# --------------------------------------------------------------------------- #

def test_a_run_needs_a_published_version(client):
    seed(client)
    resp = client.post("/api/v1/runs", json={}, headers=headers("admin"))
    assert resp.status_code == 409
    assert "publish" in resp.json()["detail"]


def test_only_an_admin_triggers_a_run(client):
    publish(client)
    assert client.post("/api/v1/runs", json={}, headers=headers("director")).status_code == 403


def test_run_writes_the_ten_step_trace_with_precedent_skipped(client):
    seed(client)
    version = publish(client)
    run = client.post("/api/v1/runs", json={}, headers=headers("admin")).json()

    assert run["status"] == "completed"
    assert run["mode"] == "mock"
    assert run["rubric_version_label"] == version["label"]
    assert [s["n"] for s in run["steps"]] == list(range(1, 11))

    by_name = {s["name"]: s for s in run["steps"]}
    # The two dashed steps in Plate 2 report skipped, with the reason.
    assert by_name["Precedent"]["status"] == "skipped"
    assert "memory" in by_name["Precedent"]["detail"]
    # Lifecycle runs even without bands: it says band crossing is undecidable
    # for this version, and it is where transition proposals are raised.
    assert by_name["Lifecycle"]["status"] == "ran"
    assert "undecidable" in by_name["Lifecycle"]["detail"]
    assert "moves nothing itself" in by_name["Lifecycle"]["detail"]
    # A run over live rows has no sealed workbook behind it, and says so.
    assert run["snapshot_id"] is None
    assert "no workbook snapshot" in by_name["Intake"]["detail"].lower()


def test_run_queues_proposals_and_does_not_change_confidence(client):
    korea, _ = seed(client)
    publish(client)
    run = client.post("/api/v1/runs", json={}, headers=headers("admin")).json()

    assert run["counts"]["queued"] == run["counts"]["proposals"]
    assert run["counts"]["auto_applied"] == 0  # no ratified bands, so nothing applies on its own
    after = client.get(f"/api/v1/opportunities/{korea['id']}").json()
    assert after["confidence"] == korea["confidence"]


def test_a_forbidden_pairing_is_blocking_and_is_not_scored(client):
    """Decision #10: an invalid (Design Status, Stage) cell is a blocking
    finding. The row is excluded from totals and never reaches the scorer,
    rather than being scored with a haircut for a contradiction a person has
    to fix first."""
    # Intake refuses a forbidden pairing outright (WBS 4.3), so a stored one
    # can only exist from before the table changed -- write it directly.
    refused = client.post("/api/v1/opportunities",
                          json={**PAYLOAD, "project": "Wrong", "stage": "Concept"},  # Design Win at Concept
                          headers=headers("director"))
    assert refused.status_code == 400 and "V-b" in refused.json()["detail"]
    from app.db.models.opportunity import Opportunity
    with client.session_factory() as db:
        db.add(Opportunity(**{**PAYLOAD, "project": "Wrong", "stage": "Concept"}))
        db.commit()
    seed(client)
    publish(client)
    run = client.post("/api/v1/runs", json={}, headers=headers("admin")).json()
    assert run["counts"]["rows_read"] == 3
    assert run["counts"]["blocked"] == 1
    assert run["counts"]["scored"] == 2
    validate = next(s for s in run["steps"] if s["name"] == "Validate")
    assert "Wrong: Design Win at Concept is forbidden" in validate["detail"]
    assert all(p["project"] != "Wrong" for p in client.get("/api/v1/proposals", headers=headers("director")).json())


def test_a_second_run_does_not_double_queue_the_same_row(client):
    seed(client)
    publish(client)
    client.post("/api/v1/runs", json={}, headers=headers("admin"))
    second = client.post("/api/v1/runs", json={}, headers=headers("admin")).json()
    assert second["counts"]["skipped_open_proposal"] == 2
    assert second["counts"]["proposals"] == 0


def test_recompute_step_reports_the_delta_from_the_same_function(client):
    seed(client)
    publish(client)
    run = client.post("/api/v1/runs", json={}, headers=headers("admin")).json()
    counts = run["counts"]
    assert counts["delta_adjusted_revenue_k"] == pytest.approx(
        counts["proposed_adjusted_revenue_k"] - counts["base_adjusted_revenue_k"]
    )


# --------------------------------------------------------------------------- #
# Resolving
# --------------------------------------------------------------------------- #

def queue(client, role="director", regions="*", actor="marc"):
    return client.get("/api/v1/proposals", headers=headers(role, regions, actor)).json()


def test_queue_is_region_scoped(client):
    seed(client)
    publish(client)
    client.post("/api/v1/runs", json={}, headers=headers("admin"))

    korea_manager = queue(client, "manager", "Korea", "kim")
    assert {p["region"] for p in korea_manager} == {"Korea"}
    assert len(queue(client)) == 2


def test_approving_applies_the_proposed_value_and_writes_an_audit_event(client):
    korea, _ = seed(client)
    publish(client)
    client.post("/api/v1/runs", json={}, headers=headers("admin"))
    proposal = next(p for p in queue(client) if p["opportunity_id"] == korea["id"])

    resolved = client.post(f"/api/v1/proposals/{proposal['id']}/resolve",
                           json={"action": "approve", "note": "agreed at the review"},
                           headers=headers("director", "*", "marc")).json()
    assert resolved["status"] == "approved"

    after = client.get(f"/api/v1/opportunities/{korea['id']}").json()
    assert after["confidence"] == pytest.approx(proposal["proposed_confidence"])

    audit = client.get("/api/v1/audit").json()
    approval = next(e for e in audit if e["kind"] == "approval")
    assert approval["actor"] == "marc"
    assert approval["actor_role"] == "director"
    assert approval["detail"] == "agreed at the review"


def test_rejecting_leaves_the_number_alone_but_still_records_the_decision(client):
    korea, _ = seed(client)
    publish(client)
    client.post("/api/v1/runs", json={}, headers=headers("admin"))
    proposal = next(p for p in queue(client) if p["opportunity_id"] == korea["id"])

    no_code = client.post(f"/api/v1/proposals/{proposal['id']}/resolve", json={"action": "reject"},
                          headers=headers("director", "*", "marc"))
    assert no_code.status_code == 400 and "rejection_reason" in no_code.json()["detail"]

    resp = client.post(f"/api/v1/proposals/{proposal['id']}/resolve",
                       json={"action": "reject", "reason_code": "factor_misfired"},
                       headers=headers("director", "*", "marc"))
    assert resp.status_code == 200, resp.text

    after = client.get(f"/api/v1/opportunities/{korea['id']}").json()
    assert after["confidence"] == korea["confidence"]
    assert any(e["kind"] == "rejection" for e in client.get("/api/v1/audit").json())


def test_an_override_must_cite_a_reason_code_from_the_vocabulary(client):
    seed(client)
    publish(client)
    client.post("/api/v1/runs", json={}, headers=headers("admin"))
    proposal = queue(client)[0]

    no_code = client.post(f"/api/v1/proposals/{proposal['id']}/resolve",
                          json={"action": "override", "value": 0.4},
                          headers=headers("director", "*", "marc"))
    assert no_code.status_code == 400
    assert "override_reason" in no_code.json()["detail"]

    bad_code = client.post(f"/api/v1/proposals/{proposal['id']}/resolve",
                           json={"action": "override", "value": 0.4, "reason_code": "because"},
                           headers=headers("director", "*", "marc"))
    assert bad_code.status_code == 400

    good = client.post(f"/api/v1/proposals/{proposal['id']}/resolve",
                       json={"action": "override", "value": 0.4, "reason_code": "new_evidence_since_proposal"},
                       headers=headers("director", "*", "marc"))
    assert good.status_code == 200
    assert good.json()["status"] == "overridden"
    assert client.get(f"/api/v1/opportunities/{proposal['opportunity_id']}").json()["confidence"] == 0.4


def test_a_reviewer_cannot_resolve_a_row_they_own(client):
    """Enforcement point 5, checked in code -- calling the API directly gets the
    same refusal a hidden button would only imply."""
    seed(client)
    publish(client)
    client.post("/api/v1/runs", json={}, headers=headers("admin"))
    proposal = next(p for p in queue(client) if p["owner"] == "jdoe")

    resp = client.post(f"/api/v1/proposals/{proposal['id']}/resolve", json={"action": "approve"},
                       headers=headers("director", "*", "jdoe"))
    assert resp.status_code == 400
    assert "own" in resp.json()["detail"]


def test_the_queue_says_ahead_of_time_why_a_control_is_disabled(client):
    seed(client)
    publish(client)
    client.post("/api/v1/runs", json={}, headers=headers("admin"))

    as_owner = queue(client, "owner", "*", "jdoe")
    assert all(not p["actionable"] for p in as_owner)
    assert "no approve grant" in as_owner[0]["blocked_reason"]

    korea_manager = client.get("/api/v1/proposals", headers=headers("manager", "Korea", "kim")).json()
    assert all(p["actionable"] for p in korea_manager)


def test_a_manager_cannot_resolve_outside_their_region(client):
    seed(client)
    publish(client)
    client.post("/api/v1/runs", json={}, headers=headers("admin"))
    europe_proposal = next(p for p in queue(client) if p["region"] == "Europe")

    resp = client.post(f"/api/v1/proposals/{europe_proposal['id']}/resolve", json={"action": "approve"},
                       headers=headers("manager", "Korea", "kim"))
    assert resp.status_code == 404  # scoped out of the query entirely, so it does not exist to them


def test_a_resolved_proposal_cannot_be_resolved_twice(client):
    seed(client)
    publish(client)
    client.post("/api/v1/runs", json={}, headers=headers("admin"))
    proposal = queue(client)[0]

    client.post(f"/api/v1/proposals/{proposal['id']}/resolve", json={"action": "approve"},
                headers=headers("director", "*", "marc"))
    again = client.post(f"/api/v1/proposals/{proposal['id']}/resolve", json={"action": "approve"},
                        headers=headers("director", "*", "marc"))
    assert again.status_code == 400
    assert "already" in again.json()["detail"]


def test_request_review_scores_one_row_through_the_same_path(client):
    korea, _ = seed(client)
    publish(client)
    created = client.post(f"/api/v1/opportunities/{korea['id']}/request-review",
                          headers=headers("owner", "Korea", "jdoe"))
    assert created.status_code == 201
    body = created.json()
    assert body["status"] == "pending"
    assert body["rubric_version_label"] == "2026.1"
    assert any(f["key"] == "named_competitor_threat" for f in body["factors"])

    duplicate = client.post(f"/api/v1/opportunities/{korea['id']}/request-review",
                            headers=headers("owner", "Korea", "jdoe"))
    assert duplicate.status_code == 409


def test_proposal_keeps_the_rejected_factors_for_the_reviewer(client):
    """"A reviewer who only ever sees what the model got right has no way to
    calibrate how much to trust the next proposal.\""""
    seed(client)
    publish(client)
    client.post("/api/v1/runs", json={}, headers=headers("admin"))
    proposal = queue(client)[0]

    guards = {f["guard"] for f in proposal["factors"] if f["guard"]}
    assert "not_assessable" in guards
    assert any(f["detail"] and "absent" in f["detail"] for f in proposal["factors"])
