"""local sign-in: auth_account and auth_session

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-17

AUTH_MODE=local (app/security/local_auth.py): an email + password credential
verified by a one-time code, and the sessions it opens. A credential grants
nothing by itself -- role and scope are still read from the app_user row an
admin provisioned for the same email.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "auth_account",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(256), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("password_hash", sa.String(256), nullable=False),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("otp_hash", sa.String(64), nullable=True),
        sa.Column("otp_purpose", sa.String(16), nullable=True),
        sa.Column("otp_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("otp_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("otp_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_auth_account_email", "auth_account", ["email"], unique=True)

    op.create_table(
        "auth_session",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("account_id", sa.String(36), sa.ForeignKey("auth_account.id"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent", sa.String(256), nullable=True),
    )
    op.create_index("ix_auth_session_account_id", "auth_session", ["account_id"])
    op.create_index("ix_auth_session_token_hash", "auth_session", ["token_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_auth_session_token_hash", table_name="auth_session")
    op.drop_index("ix_auth_session_account_id", table_name="auth_session")
    op.drop_table("auth_session")
    op.drop_index("ix_auth_account_email", table_name="auth_account")
    op.drop_table("auth_account")
