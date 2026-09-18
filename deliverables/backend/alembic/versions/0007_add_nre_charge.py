"""add the per-opportunity NRE charge

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-10

Non-recurring engineering (WBS 3.5) is one-off engineering work or a licence,
not silicon revenue. The workbook carries it as whole FCST_Revenue rows with
Design Status "NRE" -- app/calc/nre.py splits those -- but an opportunity had
nowhere to record its own charge, so any NRE entered against one would have had
to hide inside EAU x ASP and phase like silicon in every downstream quarter.

Nullable on purpose: most opportunities carry no NRE, and a null means "none on
this row" rather than a defaulted zero that would be indistinguishable from a
charge someone recorded as nothing.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("opportunity") as batch:
        batch.add_column(sa.Column("nre_charge_k", sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("opportunity") as batch:
        batch.drop_column("nre_charge_k")
