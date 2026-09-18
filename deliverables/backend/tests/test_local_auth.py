"""AUTH_MODE=local: sign-up, one-time code, sign-in, sessions -- and the rule
that a credential grants nothing until an admin provisions the email."""

import pytest

from app.core.config import settings
from app.db.models.app_user import AppUser
from app.security import local_auth

ADMIN = {"X-OppTrack-Role": "admin", "X-OppTrack-Actor": "root", "X-OppTrack-Regions": "*"}


@pytest.fixture()
def local(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "local")
    monkeypatch.setattr(settings, "otp_delivery", "console")
    return client


def provision(client, email, role="director", region_scope="*", user_id=None):
    """Provisioning is an admin act; the test does it straight in the DB so it
    does not depend on the header stand-in being on at the same time."""
    with client.session_factory() as db:
        db.add(AppUser(user_id=user_id or email.split("@")[0], email=email, display_name="P",
                       role=role, region_scope=region_scope, provisioned_by="root"))
        db.commit()


def signup_and_verify(client, email="marc@axcelai.com", password="correct-horse-battery"):
    sent = client.post("/api/v1/auth/signup", json={"email": email, "display_name": "Marc", "password": password})
    assert sent.status_code == 201, sent.text
    body = sent.json()
    assert body["delivery"] == "console" and body["dev_code"] and len(body["dev_code"]) == 6
    verified = client.post("/api/v1/auth/verify", json={"email": email, "code": body["dev_code"]})
    assert verified.status_code == 200, verified.text
    return verified.json()["token"]


def test_config_reports_the_mode(local):
    assert local.get("/api/v1/auth/config").json()["mode"] == "local"


def test_auth_routes_are_off_unless_local(client):
    assert client.post("/api/v1/auth/signup", json={"email": "a@b.co", "display_name": "A", "password": "x" * 12}).status_code == 404


def test_signup_verify_login_gives_a_session_that_carries_the_provisioned_role(local):
    provision(local, "marc@axcelai.com", role="director")
    token = signup_and_verify(local)

    me = local.get("/api/v1/access/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200, me.text
    assert me.json()["role"] == "director" and me.json()["user_id"] == "marc"

    session = local.get("/api/v1/auth/session", headers={"Authorization": f"Bearer {token}"}).json()
    assert session["provisioned"] is True and session["role_label"]

    # Sign in again with the password: a second session.
    login = local.post("/api/v1/auth/login", json={"email": "MARC@axcelai.com", "password": "correct-horse-battery"})
    assert login.status_code == 200
    assert local.get("/api/v1/opportunities", headers={"Authorization": f"Bearer {login.json()['token']}"}).status_code == 200


def test_headers_are_ignored_in_local_mode(local):
    resp = local.get("/api/v1/opportunities", headers=ADMIN | {"X-OppTrack-Role": "director"})
    assert resp.status_code == 401
    assert "sign in" in resp.json()["detail"]


def test_a_credential_without_a_provisioned_row_has_no_rights(local):
    token = signup_and_verify(local, email="stranger@example.com")
    session = local.get("/api/v1/auth/session", headers={"Authorization": f"Bearer {token}"}).json()
    assert session["provisioned"] is False and session["role"] is None
    blocked = local.get("/api/v1/opportunities", headers={"Authorization": f"Bearer {token}"})
    assert blocked.status_code == 403
    assert "ask an admin" in blocked.json()["detail"]
    # The moment an admin provisions the email, the same session works.
    provision(local, "stranger@example.com", role="owner", region_scope="Korea")
    assert local.get("/api/v1/opportunities", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_wrong_code_five_times_locks_the_code(local):
    sent = local.post("/api/v1/auth/signup", json={"email": "kim@axcelai.com", "display_name": "Kim", "password": "long-enough-pass"}).json()
    for left in (4, 3, 2, 1, 0):
        r = local.post("/api/v1/auth/verify", json={"email": "kim@axcelai.com", "code": "000000"})
        assert r.status_code == 401, r.text
        if left:
            assert f"{left} attempt" in r.json()["detail"]
    locked = local.post("/api/v1/auth/verify", json={"email": "kim@axcelai.com", "code": sent["dev_code"]})
    assert locked.status_code == 423


def test_login_needs_a_verified_email_and_the_right_password(local):
    local.post("/api/v1/auth/signup", json={"email": "cfo@axcelai.com", "display_name": "CFO", "password": "finance-pass-2026"})
    unverified = local.post("/api/v1/auth/login", json={"email": "cfo@axcelai.com", "password": "finance-pass-2026"})
    assert unverified.status_code == 403 and "verify" in unverified.json()["detail"]
    wrong = local.post("/api/v1/auth/login", json={"email": "cfo@axcelai.com", "password": "nope-nope-nope"})
    assert wrong.status_code == 401
    unknown = local.post("/api/v1/auth/login", json={"email": "nobody@axcelai.com", "password": "nope-nope-nope"})
    assert unknown.status_code == 401 and unknown.json()["detail"] == wrong.json()["detail"]


def test_short_passwords_and_duplicate_emails_are_refused(local):
    short = local.post("/api/v1/auth/signup", json={"email": "a@axcelai.com", "display_name": "A", "password": "short"})
    assert short.status_code == 400 and "10 characters" in short.json()["detail"]
    signup_and_verify(local, email="a@axcelai.com", password="a-long-password")
    dup = local.post("/api/v1/auth/signup", json={"email": "a@axcelai.com", "display_name": "A", "password": "a-long-password"})
    assert dup.status_code == 409


def test_logout_revokes_the_session(local):
    provision(local, "marc@axcelai.com")
    token = signup_and_verify(local)
    h = {"Authorization": f"Bearer {token}"}
    assert local.post("/api/v1/auth/logout", headers=h).status_code == 204
    assert local.get("/api/v1/access/me", headers=h).status_code == 401


def test_password_reset_by_code_invalidates_open_sessions(local):
    provision(local, "marc@axcelai.com")
    token = signup_and_verify(local)
    sent = local.post("/api/v1/auth/reset/start", json={"email": "marc@axcelai.com"}).json()
    assert sent["dev_code"]
    done = local.post("/api/v1/auth/reset/finish", json={"email": "marc@axcelai.com", "code": sent["dev_code"], "new_password": "brand-new-password"})
    assert done.status_code == 204
    assert local.get("/api/v1/access/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    assert local.post("/api/v1/auth/login", json={"email": "marc@axcelai.com", "password": "brand-new-password"}).status_code == 200


def test_nothing_secret_is_stored_in_clear(local):
    sent = local.post("/api/v1/auth/signup", json={"email": "s@axcelai.com", "display_name": "S", "password": "secret-password-1"}).json()
    with local.session_factory() as db:
        account = local_auth.get_account(db, "s@axcelai.com")
        assert "secret-password-1" not in account.password_hash
        assert account.password_hash.startswith("pbkdf2_sha256$")
        assert account.otp_hash != sent["dev_code"] and len(account.otp_hash) == 64


def test_smtp_delivery_never_returns_the_code(local, monkeypatch):
    monkeypatch.setattr(settings, "otp_delivery", "smtp")
    captured = {}

    def fake_send(to, subject, body):
        captured["body"] = body
        return "smtp"

    monkeypatch.setattr(local_auth, "send_email", fake_send)
    sent = local.post("/api/v1/auth/signup", json={"email": "g@gmail.com", "display_name": "G", "password": "gmail-user-pass"}).json()
    assert sent["delivery"] == "smtp" and sent["dev_code"] is None
    assert "code" in captured["body"]


def test_a_deactivated_person_is_told_so_not_asked_to_wait(local):
    provision(local, "marc@axcelai.com")
    token = signup_and_verify(local)
    with local.session_factory() as db:
        from sqlalchemy import select
        user = db.scalar(select(AppUser).where(AppUser.email == "marc@axcelai.com"))
        user.active = False
        db.commit()
    blocked = local.get("/api/v1/opportunities", headers={"Authorization": f"Bearer {token}"})
    assert blocked.status_code == 403 and "deactivated" in blocked.json()["detail"]
    assert local.get("/api/v1/auth/session", headers={"Authorization": f"Bearer {token}"}).json()["provisioned"] is False
