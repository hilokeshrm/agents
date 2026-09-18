"""platform completion: targets, actuals, notifications, users, memory, market data, webhooks, conversations

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-15

Everything the remaining WBS packages needed a table for, in one migration:

- target (G1/G2, WBS 6.4)                 Finance's top-down commitment by region and period
- actual (A1/A2, WBS 6.5, 11.4, 11.5)     shipped revenue and POS units from the connectors
- notification (WBS 11.7)                 outbound messages with delivery state
- app_user (WBS 9.4, 9.7)                 admin-provisioned identities; anonymised on delete
- memory_chunk (WBS 9.3, 7.5)             L3 semantic memory, scrubbed of numbers and pricing
- market_programme (WBS 11.6)             licensed vehicle-programme data (empty until the licence)
- webhook_subscription / webhook_delivery (WBS 10.13)
- conversation (WBS 14.5)                 every assistant question and answer

Plus three column changes: opportunity.phasing_profile (WBS 5.5, decision #66),
calibration.sd_pp and calibration.reliable (WBS 6.5, decision #70), and
finding.snapshot_id made nullable so direct-entry findings can exist (WBS 3.7).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("opportunity") as batch:
        batch.add_column(sa.Column("phasing_profile", sa.JSON(), nullable=True))
    with op.batch_alter_table("calibration") as batch:
        batch.add_column(sa.Column("sd_pp", sa.Float(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("reliable", sa.Boolean(), nullable=False, server_default=sa.false()))
    with op.batch_alter_table("finding") as batch:
        batch.alter_column("snapshot_id", existing_type=sa.String(36), nullable=True)

    op.create_table(
        "target",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("region", sa.String(64), nullable=False),
        sa.Column("period", sa.String(16), nullable=False),
        sa.Column("amount_k", sa.Float(), nullable=False),
        sa.Column("entered_by", sa.String(128), nullable=False),
        sa.Column("entered_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("region", "period", name="uq_target_region_period"),
    )
    op.create_table(
        "actual",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("opportunity_id", sa.String(36), sa.ForeignKey("opportunity.id"), nullable=True, index=True),
        sa.Column("part_number", sa.String(64), nullable=False, index=True),
        sa.Column("region", sa.String(64), nullable=True),
        sa.Column("customer", sa.String(128), nullable=True),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("quarter", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("units_kpcs", sa.Float(), nullable=True),
        sa.Column("revenue_k", sa.Float(), nullable=True),
        sa.Column("invoiced_asp", sa.Float(), nullable=True),
        sa.Column("pulled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pull_ref", sa.String(128), nullable=True),
    )
    op.create_table(
        "notification",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("recipient", sa.String(128), nullable=False),
        sa.Column("subject", sa.String(256), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("dedupe_key", sa.String(256), nullable=True, index=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("channel", sa.String(16), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "app_user",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(128), nullable=False, unique=True, index=True),
        sa.Column("email", sa.String(256), nullable=True, unique=True),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("region_scope", sa.String(256), nullable=False),
        sa.Column("idp_subject", sa.String(256), nullable=True, unique=True, index=True),
        sa.Column("api_key_hash", sa.String(64), nullable=True, index=True),
        sa.Column("connector", sa.String(64), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("provisioned_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("anonymised_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "memory_chunk",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("opportunity_id", sa.String(36), sa.ForeignKey("opportunity.id"), nullable=True, index=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("region", sa.String(64), nullable=True, index=True),
        sa.Column("product_line", sa.String(128), nullable=True, index=True),
        sa.Column("part_number", sa.String(64), nullable=True, index=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("tokens", sa.JSON(), nullable=False),
        sa.Column("embedding", sa.JSON(), nullable=True),
        sa.Column("vintage", sa.String(36), nullable=True),
        sa.Column("preserved", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True, index=True),
    )
    op.create_table(
        "market_programme",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("programme", sa.String(128), nullable=False, index=True),
        sa.Column("oem", sa.String(128), nullable=False, index=True),
        sa.Column("region", sa.String(64), nullable=True),
        sa.Column("application", sa.String(128), nullable=True),
        sa.Column("sop", sa.Date(), nullable=True),
        sa.Column("build_volume_ksets", sa.Float(), nullable=True),
        sa.Column("pulled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pull_ref", sa.String(128), nullable=True),
    )
    op.create_table(
        "webhook_subscription",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("url", sa.String(512), nullable=False),
        sa.Column("events", sa.JSON(), nullable=False),
        sa.Column("secret", sa.String(128), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "webhook_delivery",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("subscription_id", sa.String(36), sa.ForeignKey("webhook_subscription.id"), nullable=False, index=True),
        sa.Column("event", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("response_code", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "conversation",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("actor", sa.String(128), nullable=False, index=True),
        sa.Column("actor_role", sa.String(32), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("intent", sa.String(16), nullable=False),
        sa.Column("tool_calls", sa.JSON(), nullable=False),
        sa.Column("grounded", sa.Boolean(), nullable=True),
        sa.Column("untraceable", sa.JSON(), nullable=False),
        sa.Column("model_id", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    for name in ("conversation", "webhook_delivery", "webhook_subscription", "market_programme", "memory_chunk",
                 "app_user", "notification", "actual", "target"):
        op.drop_table(name)
    with op.batch_alter_table("finding") as batch:
        batch.alter_column("snapshot_id", existing_type=sa.String(36), nullable=False)
    with op.batch_alter_table("calibration") as batch:
        batch.drop_column("reliable")
        batch.drop_column("sd_pp")
    with op.batch_alter_table("opportunity") as batch:
        batch.drop_column("phasing_profile")
