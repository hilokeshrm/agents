"""
GET /registry (WBS 2.2, 2.6): the vocabularies and value sets a client must use
to send something the API will accept.

The point of these tests is that the served lists ARE the enforced lists. Each
one asserts against the module the enforcement reads, not against a literal
copied into the test -- a hardcoded expectation here would reintroduce exactly
the drift this endpoint exists to prevent.
"""

from app.registry.enums import DESIGN_STATUS_MAP, STAGE_VALUES
from app.registry.reason_codes import (
    LOSS_REASON_CODES,
    OVERRIDE_REASON_CODES,
    STAGE_EXIT_REASON_CODES,
)
from app.services.state_transitions import APPROVAL_REQUIRED_STATUSES
from tests.test_roles_and_scope import PAYLOAD, headers


def test_registry_serves_the_enforced_vocabularies(client):
    body = client.get("/api/v1/registry").json()
    codes = body["reason_codes"]

    assert set(codes["loss_reason"]["codes"]) == set(LOSS_REASON_CODES.codes)
    assert set(codes["stage_exit_reason"]["codes"]) == set(STAGE_EXIT_REASON_CODES.codes)
    assert set(codes["override_reason"]["codes"]) == set(OVERRIDE_REASON_CODES.codes)


def test_it_reports_the_vocabularies_as_draft(client):
    """Enforcement is real; the category lists are not signed off. A screen that
    shows them should be able to say so."""
    codes = client.get("/api/v1/registry").json()["reason_codes"]
    assert all(v["ratified"] is False for v in codes.values())
    assert codes["loss_reason"]["required_when"] == "design status becomes Lost"


def test_canonical_values_are_deduplicated_to_one_entry_per_status(client):
    body = client.get("/api/v1/registry").json()
    assert body["design_statuses"] == list(dict.fromkeys(DESIGN_STATUS_MAP.values()))
    assert len(body["design_statuses"]) == len(set(body["design_statuses"]))
    assert body["stages"] == list(STAGE_VALUES)


def test_approval_required_statuses_match_the_gate_the_route_applies(client):
    body = client.get("/api/v1/registry").json()
    assert {s.lower() for s in body["approval_required_statuses"]} == set(APPROVAL_REQUIRED_STATUSES)


def test_every_served_status_is_actually_transitionable(client):
    """A status offered here must be one record_transition accepts, so a UI built
    from this list cannot render a control that always fails."""
    created = client.post("/api/v1/opportunities", json=PAYLOAD, headers=headers("director")).json()
    served = client.get("/api/v1/registry").json()

    for status in served["design_statuses"]:
        reason = "cancellation" if status.lower() == "lost" else None
        resp = client.post(
            f"/api/v1/opportunities/{created['id']}/transition",
            json={"field": "design_status", "to_value": status, "actor": "marc", "reason_code": reason},
            headers=headers("director"),
        )
        assert resp.status_code == 201, f"{status}: {resp.text}"

    for stage in served["stages"]:
        resp = client.post(
            f"/api/v1/opportunities/{created['id']}/transition",
            json={"field": "stage", "to_value": stage, "actor": "marc"},
            headers=headers("director"),
        )
        assert resp.status_code == 201, f"{stage}: {resp.text}"
