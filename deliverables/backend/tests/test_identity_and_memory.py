"""
Identity (WBS 9.4, 9.5, 12.5), retention (9.7), the gateway (10.1), and L3
memory with the evidence assembler (9.3, 7.5).
"""

import time
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.config import settings
from app.security import oidc
from tests.test_roles_and_scope import PAYLOAD, headers

ISSUER = "https://idp.example.test/"
AUDIENCE = "opptrack"


@pytest.fixture()
def sso(monkeypatch):
    """A real RS256 issuer: a fresh keypair, tokens signed with it, and the
    JWKS lookup stubbed to return the public key."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    monkeypatch.setattr(settings, "auth_issuer", ISSUER)
    monkeypatch.setattr(settings, "auth_audience", AUDIENCE)
    monkeypatch.setattr(oidc, "_signing_key", lambda token: public_pem)

    def token(sub: str, email: str | None = None, **claims):
        payload = {"iss": ISSUER, "aud": AUDIENCE, "sub": sub, "exp": int(time.time()) + 300, **claims}
        if email:
            payload["email"] = email
        return jwt.encode(payload, key, algorithm="RS256", headers={"kid": "test"})

    return token


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------- #
# 9.4 -- SSO, provisioning, no self-registration
# --------------------------------------------------------------------------- #

def test_with_sso_on_the_header_stand_in_is_ignored_and_a_token_is_required(client, sso):
    assert client.get("/api/v1/opportunities", headers=headers("director")).status_code == 401
    assert client.get("/api/v1/opportunities", headers=bearer("not.a.token")).status_code == 401


def test_a_signed_in_but_unprovisioned_user_is_refused_there_is_no_self_registration(client, sso):
    resp = client.get("/api/v1/opportunities", headers=bearer(sso("sub-1", "kim@axcelai.com")))
    assert resp.status_code == 403 and "not provisioned" in resp.json()["detail"]
    # No route creates an account from a token; only an admin provisions.
    assert client.post("/api/v1/users", json={"user_id": "kim", "display_name": "Kim", "role": "owner"},
                       headers=bearer(sso("sub-1", "kim@axcelai.com"))).status_code == 403


def test_role_and_scope_come_from_the_provisioned_row_not_the_token(client, sso, monkeypatch):
    # Bootstrap the first admin the way an operator would: directly in the table.
    from app.db.models.app_user import AppUser
    with client.session_factory() as db:
        db.add(AppUser(user_id="root", display_name="Root", role="admin", region_scope="*",
                       idp_subject="sub-root", provisioned_by="bootstrap"))
        db.commit()
    admin = bearer(sso("sub-root"))
    created = client.post("/api/v1/users", json={
        "user_id": "kim", "display_name": "Kim", "email": "Kim@AxcelAI.com", "role": "manager", "region_scope": "KR",
    }, headers=admin)
    assert created.status_code == 201 and created.json()["region_scope"] == "Korea"

    # Kim signs in with a token claiming to be a director over every region.
    # The claim is ignored: the row says manager, Korea.
    kim = bearer(sso("sub-kim", "kim@axcelai.com", opptrack_role="director", opptrack_regions="*"))
    me = client.get("/api/v1/access/me", headers=kim).json()
    assert me["role"] == "manager"
    # First sign-in bound the subject to the provisioned row.
    users = {u["user_id"]: u for u in client.get("/api/v1/users", headers=admin).json()}
    assert users["kim"]["idp_subject"] == "sub-kim"

    # Region scope is enforced in the query: an EU row does not exist for Kim.
    with monkeypatch.context() as m:
        m.setattr(settings, "auth_issuer", None)   # seed through the dev path
        eu = client.post("/api/v1/opportunities", json={**PAYLOAD, "region": "Europe", "customer": "ODE"},
                         headers=headers("director")).json()
        kr = client.post("/api/v1/opportunities", json=PAYLOAD, headers=headers("director")).json()
    assert {o["id"] for o in client.get("/api/v1/opportunities", headers=kim).json()} == {kr["id"]}
    assert client.get(f"/api/v1/opportunities/{eu['id']}", headers=kim).status_code == 404

    # Deactivation is immediate.
    client.patch("/api/v1/users/kim", json={"active": False}, headers=admin)
    assert client.get("/api/v1/access/me", headers=kim).status_code == 403


def test_a_service_account_authenticates_with_its_key_and_cannot_act_as_a_person(client, sso):
    from app.db.models.app_user import AppUser
    with client.session_factory() as db:
        db.add(AppUser(user_id="root", display_name="Root", role="admin", idp_subject="sub-root", provisioned_by="bootstrap"))
        db.commit()
    admin = bearer(sso("sub-root"))
    svc = client.post("/api/v1/users/service", json={"user_id": "crm-sync", "display_name": "CRM sync",
                                                      "role": "service", "connector": "crm"}, headers=admin).json()
    key = svc["api_key"]
    assert key.startswith("opk_")
    assert client.get("/api/v1/access/me", headers={"X-OppTrack-Api-Key": key}).json()["role"] == "service"
    assert client.get("/api/v1/access/me", headers={"X-OppTrack-Api-Key": "opk_wrong"}).status_code == 401
    # The roles matrix: a service account never enters a confidence or moves a record.
    assert client.post("/api/v1/opportunities", json=PAYLOAD, headers={"X-OppTrack-Api-Key": key}).status_code == 403
    # Only the hash is stored.
    assert "api_key" not in client.get("/api/v1/users", headers=admin).json()[1]


def test_anonymise_on_delete_keeps_the_decisions(client, sso):
    from app.db.models.app_user import AppUser
    with client.session_factory() as db:
        db.add(AppUser(user_id="root", display_name="Root", role="admin", idp_subject="sub-root", provisioned_by="bootstrap"))
        db.add(AppUser(user_id="marc", display_name="Marc D", email="marc@axcelai.com", role="director",
                       idp_subject="sub-marc", provisioned_by="root"))
        db.commit()
    admin, marc = bearer(sso("sub-root")), bearer(sso("sub-marc"))
    opp = client.post("/api/v1/opportunities", json={**PAYLOAD, "design_status": "Design In", "stage": "DVT",
                                                     "confidence": 0.65}, headers=marc).json()
    client.post(f"/api/v1/opportunities/{opp['id']}/transition",
                json={"field": "design_status", "to_value": "Lost", "reason_code": "price", "actor": "marc"}, headers=marc)

    gone = client.delete("/api/v1/users/marc", headers=admin).json()
    assert gone["display_name"].startswith("former user") and gone["email"] is None and gone["active"] is False
    assert client.get("/api/v1/access/me", headers=marc).status_code == 403
    # The decision stands, under the same actor id.
    history = client.get(f"/api/v1/opportunities/{opp['id']}/state-history", headers=admin)
    assert history.status_code in (200, 404)  # admin sees no pipeline rows by design
    with client.session_factory() as db:
        from app.db.models.state_history import StateHistory
        rows = db.query(StateHistory).filter_by(opportunity_id=opp["id"], to_value="Lost").all()
        assert rows and rows[0].actor == "marc"
    assert client.delete("/api/v1/users/root", headers=admin).status_code == 400


# --------------------------------------------------------------------------- #
# 10.1 -- the gateway
# --------------------------------------------------------------------------- #

def test_every_response_carries_a_request_id_and_echoes_a_supplied_one(client):
    r = client.get("/health")
    assert len(r.headers["X-Request-ID"]) == 16
    r = client.get("/health", headers={"X-Request-ID": "trace-abc"})
    assert r.headers["X-Request-ID"] == "trace-abc"
    spec = client.get("/openapi.json").json()
    assert {t["name"] for t in spec["tags"]} >= {"opportunities", "review", "rubric", "analyses", "users"}


# --------------------------------------------------------------------------- #
# 9.3 / 7.5 -- memory: scrub, filter, rank, budget, expire
# --------------------------------------------------------------------------- #

def test_numbers_and_pricing_are_never_stored():
    from app.memory import scrub

    clean = scrub("Design review passed in March. Resale ASP agreed at $4.30 per unit. "
                  "EAU could reach 10,000 Kpcs by 2028; customer wants dual sourcing.")
    assert "4.30" not in clean and "ASP" not in clean and "Resale" not in clean
    assert "10,000" not in clean and "2028" not in clean
    assert "dual sourcing" in clean and "Design review passed" in clean


def test_assembler_filters_before_it_ranks_and_respects_the_budget(client):
    from app.memory import assemble, remember

    kr = client.post("/api/v1/opportunities", json={**PAYLOAD, "project": "KR-1", "product_line": "SerDes",
                                                    "evidence": "Customer requires dual sourcing on this socket."},
                     headers=headers("director")).json()
    eu = client.post("/api/v1/opportunities", json={**PAYLOAD, "project": "EU-1", "region": "Europe", "customer": "ODE",
                                                    "product_line": "SerDes"}, headers=headers("director")).json()
    subject = client.post("/api/v1/opportunities", json={**PAYLOAD, "project": "KR-2", "product_line": "SerDes",
                                                         "evidence": "Second source requested; dual sourcing likely."},
                          headers=headers("director")).json()
    with client.session_factory() as db:
        from app.db.models.opportunity import Opportunity
        o_kr, o_eu, o_subject = (db.get(Opportunity, x["id"]) for x in (kr, eu, subject))
        remember(db, opportunity=o_kr, kind="comment", text="Customer requires dual sourcing on this socket; second source named.")
        remember(db, opportunity=o_eu, kind="comment", text="Dual sourcing demanded by the OEM; second source named.")
        # A note about price is dropped whole by the scrub -- it never becomes precedent.
        assert remember(db, opportunity=o_kr, kind="loss_writeup", text="Lost a similar socket on price last year.") is None
        remember(db, opportunity=o_kr, kind="loss_writeup", text="Lost a similar socket on relationship last year.")
        db.commit()
        pack = assemble(db, opportunity=o_subject)
        # The EU note is more similar but is filtered out before ranking: wrong region.
        assert all(p.region == "Korea" for p in pack.precedents)
        assert pack.precedents and "dual sourcing" in pack.precedents[0].text
        assert pack.filtered_candidates == 2
        # The row's own notes are never its own precedent.
        assert all(p.opportunity_id != o_subject.id for p in pack.precedents)
        # A tiny budget keeps only what fits.
        assert len(assemble(db, opportunity=o_subject, token_budget=15).precedents) <= 1


def test_semantic_memory_expires_after_eight_quarters_unless_preserved(client):
    from app.memory import EIGHT_QUARTERS, remember
    from app.services.retention import enforce_retention

    opp = client.post("/api/v1/opportunities", json=PAYLOAD, headers=headers("director")).json()
    with client.session_factory() as db:
        from app.db.models.opportunity import Opportunity
        o = db.get(Opportunity, opp["id"])
        remember(db, opportunity=o, kind="comment", text="Design review passed and PPAP scheduled after summer.")
        remember(db, opportunity=o, kind="loss_writeup", text="Lost to a competitor on relationship; keep this one.", preserved=True)
        db.commit()
        report = enforce_retention(db, now=datetime.now(timezone.utc) + EIGHT_QUARTERS + timedelta(days=1))
        db.commit()
        assert report.semantic_expired == 1 and report.semantic_live == 1
        assert report.episodic_rows >= 2 and report.episodic_within_policy is True
        assert report.policy["episodic"].startswith("immutable")
