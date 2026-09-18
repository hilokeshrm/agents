"""proposal kinds and flags, reviewer feedback details, the OPP-000001 sequence

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-15

Three things the decision register's adoption needed a home for:

- proposal.kind / transition / flags (WBS 8.3, 7.4): a proposal is now either
  a confidence proposal or a lifecycle transition proposal, both in one queue;
  `flags` records what the bounds did to it (run cap clipped, clamped to the
  ceiling, contract violation), and any flag forces the review queue.
- confidence_event.details (WBS 8.7): structured reviewer feedback --
  which rubric factors a rejection or override disagreed with -- so
  rejections aggregate per factor.
- opportunity_sequence (WBS 2.4, decision #56): the counter behind the
  human-readable OPP-000001 id. Existing rows keep the ids they have; only
  newly minted ids are sequential.

Existing proposals are all confidence proposals with no flags; existing
events have no structured feedback. Both defaults say exactly that.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("proposal") as batch:
        batch.add_column(sa.Column("kind", sa.String(16), nullable=False, server_default="confidence"))
        batch.add_column(sa.Column("transition", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("flags", sa.JSON(), nullable=False, server_default="{}"))
    with op.batch_alter_table("confidence_event") as batch:
        batch.add_column(sa.Column("details", sa.JSON(), nullable=True))
    op.create_table(
        "opportunity_sequence",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("issued_to", sa.String(36), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("opportunity_sequence")
    with op.batch_alter_table("confidence_event") as batch:
        batch.drop_column("details")
    with op.batch_alter_table("proposal") as batch:
        batch.drop_column("flags")
        batch.drop_column("transition")
        batch.drop_column("kind")
