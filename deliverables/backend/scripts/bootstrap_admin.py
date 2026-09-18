"""Creates the one app_user + auth_account row a fresh deployment needs to
get started under AUTH_MODE=local: after this, that person can sign in and
use the Users screen to provision everyone else. See
docs/rollout-and-training.md step 2 -- "one row in app_user with role admin
... inserted by the operator" -- this is that row.

Chicken-and-egg reason this exists rather than using the sign-up screen: a
self-signed-up account has no role until an admin's app_user row names its
email (app/api/v1/users.py -- "the only way an identity comes into existence
... there is no sign-up route" for *roles*), and there is no admin yet to do
that naming. Run this once; do not leave it lying around as a way to mint
more admins later -- use the Users screen for that.

    python -m scripts.bootstrap_admin --email you@example.com --name "Your Name" --password 'a real password'

Idempotent: re-running with the same email updates that row (e.g. to change
the password) rather than creating a second one.
"""

import argparse
import os
import sys
from datetime import datetime, timezone

from sqlalchemy import select

from app.db.models.app_user import AppUser
from app.db.models.auth_account import AuthAccount
from app.db.session import SessionLocal
from app.security.local_auth import hash_password


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True, help="Display name")
    parser.add_argument("--user-id", default=None, help="Defaults to the email's local part")
    parser.add_argument(
        "--password", default=None,
        help="Or set OPPTRACK_ADMIN_PASSWORD instead, to keep it out of shell history",
    )
    args = parser.parse_args(argv)

    password = args.password or os.environ.get("OPPTRACK_ADMIN_PASSWORD")
    if not password:
        parser.error("--password or OPPTRACK_ADMIN_PASSWORD is required")
    if len(password) < 8:
        parser.error("password is too short (8+ characters)")

    email = args.email.strip().lower()
    user_id = args.user_id or email.split("@")[0]
    now = datetime.now(timezone.utc)

    with SessionLocal() as db:
        user = db.scalar(select(AppUser).where(AppUser.user_id == user_id))
        if user is None:
            user = AppUser(
                user_id=user_id, display_name=args.name, role="admin", region_scope="*",
                email=email, provisioned_by="bootstrap_admin",
            )
            db.add(user)
        else:
            user.email, user.role, user.region_scope, user.display_name, user.active = (
                email, "admin", "*", args.name, True,
            )

        account = db.scalar(select(AuthAccount).where(AuthAccount.email == email))
        if account is None:
            account = AuthAccount(
                email=email, display_name=args.name, password_hash=hash_password(password),
                email_verified_at=now, active=True,
            )
            db.add(account)
        else:
            account.password_hash = hash_password(password)
            account.email_verified_at = account.email_verified_at or now
            account.active = True

        db.commit()

    print(f"Admin ready: {email} (user_id={user_id}). Sign in at the app's login screen with that email and password.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
