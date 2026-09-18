"""add stable external opportunity IDs and append-only owner history"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("opportunity") as batch:
        batch.add_column(sa.Column("external_id", sa.String(length=32), nullable=True))

    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id FROM opportunity")).fetchall()
    for row in rows:
        external_id = f"OPP-{row[0].replace('-', '')[:12].upper()}"
        bind.execute(
            sa.text("UPDATE opportunity SET external_id = :external_id WHERE id = :id"),
            {"external_id": external_id, "id": row[0]},
        )

    with op.batch_alter_table("opportunity") as batch:
        batch.alter_column("external_id", existing_type=sa.String(length=32), nullable=False)
        batch.create_index("ix_opportunity_external_id", ["external_id"], unique=True)

    op.create_table(
        "owner_history",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("opportunity_id", sa.String(length=36), nullable=False),
        sa.Column("from_owner", sa.String(length=128), nullable=True),
        sa.Column("to_owner", sa.String(length=128), nullable=False),
        sa.Column("actor", sa.String(length=128), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["opportunity_id"], ["opportunity.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_owner_history_opportunity_id", "owner_history", ["opportunity_id"], unique=False)

    # Preserve the current owner as the first event for historical rows.
    bind.execute(sa.text(
        "INSERT INTO owner_history (opportunity_id, from_owner, to_owner, actor, occurred_at) "
        "SELECT id, NULL, owner, owner, created_at FROM opportunity"
    ))


def downgrade() -> None:
    op.drop_index("ix_owner_history_opportunity_id", table_name="owner_history")
    op.drop_table("owner_history")
    with op.batch_alter_table("opportunity") as batch:
        batch.drop_index("ix_opportunity_external_id")
        batch.drop_column("external_id")
