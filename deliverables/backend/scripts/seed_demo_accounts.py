"""Seeds the five demo people for AUTH_MODE=local: an admin-provisioned
app_user row (the role) and a verified sign-in credential (the password)
for each, so the platform can be tested through the real sign-in screen.

    python -m scripts.seed_demo_accounts                # password OppTrack-2026!
    python -m scripts.seed_demo_accounts --password X   # your own

Idempotent: existing rows are updated, never duplicated. Development only --
the walkthrough database, not a customer's. Run scripts/dev_up.ps1 afterwards.
"""

import sys
from datetime import datetime, timezone

from sqlalchemy import select

from app.db.models.app_user import AppUser
from app.db.models.auth_account import AuthAccount
from app.db.session import SessionLocal
from app.security.local_auth import hash_password

DEFAULT_PASSWORD = "OppTrack-2026!"

# user_id, display name, role, region scope. Emails are <user_id>@axcelai.com.
PEOPLE = [
    ("marc", "Marc (Sales Director)", "director", "*"),
    ("owner-korea", "Owner Korea (Sales owner)", "owner", "*"),
    ("kim", "Kim (Korea manager)", "manager", "Korea"),
    ("cfo", "CFO (Finance)", "finance", "*"),
    ("root", "Root (Admin)", "admin", "*"),
]


def main(argv: list[str]) -> int:
    password = argv[argv.index("--password") + 1] if "--password" in argv else DEFAULT_PASSWORD
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        for user_id, name, role, scope in PEOPLE:
            email = f"{user_id}@axcelai.com"
            user = db.scalar(select(AppUser).where(AppUser.user_id == user_id))
            if user is None:
                user = AppUser(user_id=user_id, display_name=name, role=role, region_scope=scope,
                               email=email, provisioned_by="seed_demo_accounts")
                db.add(user)
            else:
                user.email, user.role, user.region_scope, user.active = email, role, scope, True
            account = db.scalar(select(AuthAccount).where(AuthAccount.email == email))
            if account is None:
                account = AuthAccount(email=email, display_name=name, password_hash=hash_password(password),
                                      email_verified_at=now)
                db.add(account)
            else:
                account.password_hash = hash_password(password)
                account.email_verified_at = account.email_verified_at or now
                account.active = True
            print(f"{email:<28} {role:<9} regions {scope:<6} password {password}")
        db.commit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
