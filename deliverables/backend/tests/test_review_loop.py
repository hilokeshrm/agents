"""
The review loop's four guarantees (WBS 8.2, 8.4, 8.6, 8.7).

- 8.2  No mutation path can change or delete an audit event, for any role.
- 8.4  No opportunity reaches a terminal state without a reason code from the
       agreed vocabulary.
- 8.6  The post-approval figure is byte-identical to running the calc engine
       directly on the approved value -- no second model call, no cached figure.
- 8.7  Rejection reasons aggregate per rubric factor.
"""

import pytest

from app.calc.engine import compute_project_financials
from app.db.immutable import ImmutableRowError
from app.db.models.confidence_event import ConfidenceEvent
from app.db.models.opportunity import Opportunity
from app.db.models.owner_history import OwnerHistory
from app.db.models.snapshot import Snapshot
from app.db.models.state_history import StateHistory
from app.services.financials import engine_row
from tests.test_judgment_layer import load_nine
from tests.test_roles_and_scope import PAYLOAD, headers


def run_v1(client):
    ids = load_nine(client)
    client.post("/api/v1/rubric/publish-v1", headers=headers("admin"))
    client.post("/api/v1/runs", json={}, headers=headers("admin"))
    return ids, {p["project"]: p for p in client.get("/api/v1/proposals", headers=headers("director")).json()}


# --------------------------------------------------------------------------- #
# 8.2
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("model", [ConfidenceEvent, StateHistory, OwnerHistory, Snapshot])
def test_audit_rows_cannot_be_updated_or_deleted_by_anyone(client, model):
    """The guard is in the ORM, below every role: an admin session and an
    owner session hit the same refusal, because the check does not know what
    a role is."""
    run_v1(client)
    if model is Snapshot:
        client.post("/api/v1/imports/dry-run",
                    files={"file": ("p.csv", b"Region,Customer\nKorea,SLM\n", "text/csv")},
                    headers=headers("owner", "*", "jdoe"))
    with client.session_factory() as db:
        row = db.query(model).first()
        assert row is not None, f"no {model.__tablename__} row to test against"
        # Update: refused at flush.
        for attr in ("note", "actor", "source_uri"):
            if hasattr(row, attr):
                setattr(row, attr, "tampered")
                break
        else:
            row.occurred_at = row.occurred_at
            row.opportunity_id = row.opportunity_id
        with pytest.raises(ImmutableRowError):
            db.flush()
        db.rollback()
        # Delete: refused at flush.
        row = db.query(model).first()
        db.delete(row)
        with pytest.raises(ImmutableRowError):
            db.flush()
        db.rollback()
        assert db.query(model).count() >= 1


def test_the_audit_endpoint_has_no_write_methods(client):
    for method in ("put", "patch", "delete"):
        assert getattr(client, method)("/api/v1/audit", headers=headers("admin")).status_code == 405


# --------------------------------------------------------------------------- #
# 8.4
# --------------------------------------------------------------------------- #

def test_no_opportunity_reaches_lost_without_a_reason_code_from_the_vocabulary(client):
    opp = client.post("/api/v1/opportunities", json={**PAYLOAD, "design_status": "Design In", "stage": "DVT",
                                                     "confidence": 0.8}, headers=headers("director")).json()
    url = f"/api/v1/opportunities/{opp['id']}/transition"
    no_code = client.post(url, json={"field": "design_status", "to_value": "Lost", "actor": "marc"}, headers=headers("director"))
    assert no_code.status_code == 400 and "loss_reason" in no_code.json()["detail"]
    bad_code = client.post(url, json={"field": "design_status", "to_value": "Lost", "reason_code": "vibes", "actor": "marc"},
                           headers=headers("director"))
    assert bad_code.status_code == 400
    # Decision #43's list is the one enforced.
    for code in ("price", "technical_fit", "competitor", "relationship", "timing", "cancellation", "other"):
        assert code in bad_code.json()["detail"]
    ok = client.post(url, json={"field": "design_status", "to_value": "Lost", "reason_code": "competitor", "actor": "marc"},
                     headers=headers("director"))
    assert ok.status_code == 201 and ok.json()["reason_code"] == "competitor"
    assert client.get(f"/api/v1/opportunities/{opp['id']}").json()["design_status"] == "Lost"


def test_a_terminal_move_needs_a_manager_or_director(client):
    opp = client.post("/api/v1/opportunities", json=PAYLOAD, headers=headers("director")).json()
    resp = client.post(f"/api/v1/opportunities/{opp['id']}/transition",
                       json={"field": "design_status", "to_value": "Mass Production", "actor": "jdoe"},
                       headers=headers("owner", "*", "jdoe"))
    assert resp.status_code == 403


# --------------------------------------------------------------------------- #
# 8.6
# --------------------------------------------------------------------------- #

def test_post_approval_figure_is_the_calc_engine_on_the_approved_value(client):
    ids, proposals = run_v1(client)
    hermes = proposals["Hermes"]
    assert hermes["proposed_confidence"] == pytest.approx(0.20)

    resolved = client.post(f"/api/v1/proposals/{hermes['id']}/resolve", json={"action": "approve"},
                           headers=headers("director", "*", "marc")).json()
    assert resolved["status"] == "approved"

    with client.session_factory() as db:
        opp = db.get(Opportunity, ids["Hermes"])
        assert opp.confidence == pytest.approx(0.20)
        direct = compute_project_financials(engine_row(opp))
    read = client.get(f"/api/v1/opportunities/{ids['Hermes']}").json()
    # Byte-identical: the read model's figure is the engine's figure, and the
    # engine's figure is 10,000 x $4.00 x 0.20.
    assert read["adjusted_revenue_k"] == direct.adjusted_revenue_k          # identical, not approximately
    assert direct.adjusted_revenue_k == pytest.approx(8000.0)
    assert resolved["proposed_adjusted_revenue_k"] == direct.adjusted_revenue_k
    # And the portfolio total moved by exactly that row's delta.
    assert client.get("/api/v1/dashboard", headers=headers("director")).json()["total_pipeline_k"] == pytest.approx(30915.0 - 4000.0)


def test_an_override_recomputes_from_the_overridden_value(client):
    ids, proposals = run_v1(client)
    apollo = proposals["Apollo"]
    client.post(f"/api/v1/proposals/{apollo['id']}/resolve",
                json={"action": "override", "value": 0.45, "reason_code": "new_evidence_since_proposal"},
                headers=headers("director", "*", "marc"))
    read = client.get(f"/api/v1/opportunities/{ids['Apollo']}").json()
    assert read["confidence"] == 0.45 and read["adjusted_revenue_k"] == pytest.approx(10000 * 0.45)


# --------------------------------------------------------------------------- #
# 8.7
# --------------------------------------------------------------------------- #

def test_rejections_aggregate_per_rubric_factor(client):
    ids, proposals = run_v1(client)
    # Reject Hermes citing J-05 explicitly; reject Hugo with no factor named
    # (attributed to everything that fired -- J-05); override Yellowstone.
    client.post(f"/api/v1/proposals/{proposals['Hermes']['id']}/resolve",
                json={"action": "reject", "reason_code": "magnitude_too_large", "rejected_factors": ["J-05"]},
                headers=headers("director", "*", "marc"))
    client.post(f"/api/v1/proposals/{proposals['Hugo']['id']}/resolve",
                json={"action": "reject", "reason_code": "factor_misfired"},
                headers=headers("director", "*", "marc"))
    client.post(f"/api/v1/proposals/{proposals['Yellowstone']['id']}/resolve",
                json={"action": "override", "value": 0.9, "reason_code": "submitter_correction",
                      "rejected_factors": ["design_win_lock_in"]},
                headers=headers("director", "*", "marc"))

    feedback = client.get("/api/v1/rubric/feedback", headers=headers("admin")).json()
    assert feedback["proposals"] == 9 and feedback["rejections"] == 2 and feedback["overrides"] == 1
    by = {f["rule_id"]: f for f in feedback["by_factor"]}
    # J-05 fired on six rows: Hermes, Poseidon, Apollo, Hugo, Dresden, Yellowstone.
    assert by["J-05"]["fired"] == 6 and by["J-05"]["rejected"] == 2
    assert by["J-05"]["rejection_rate"] == pytest.approx(2 / 6)
    assert by["J-03"]["fired"] == 2 and by["J-03"]["overridden"] == 1
    assert by["J-01"]["fired"] == 0 and by["J-01"]["rejection_rate"] is None

    audit = client.get("/api/v1/audit", headers=headers("director")).json()
    rejections = [e for e in audit if e["kind"] == "rejection"]
    assert {e["reason_code"] for e in rejections} == {"magnitude_too_large", "factor_misfired"}
