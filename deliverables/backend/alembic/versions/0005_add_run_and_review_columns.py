"""add run table, proposal run link and band flag, confidence_event audit columns

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-07

Adds what the review console (WBS 10.5) and the runs & audit viewer (WBS 10.9)
need to be readings of stored facts rather than re-derivations:

- `run`, the twelfth table: one row per ten-step judgment pass, with its step
  trace, so a run can be opened and read back instead of re-executed to be
  explained.
- `proposal.run_id` / `proposal.band_crossing`: which run raised a proposal, and
  whether it had to reach a person. `band_crossing` is nullable because no
  lifecycle bands are ratified yet (WBS 1.1 Q1) -- null means "unknown, so it
  queued", never "no band crossed, so it auto-applied".
- `confidence_event.actor_role` / `reason_code` / `note`: actor and role written
  with every mutation, and the override reason code enforced against
  app/registry/reason_codes.py rather than accepted as prose.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0005'
down_revision: Union[str, None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'run',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('kind', sa.String(length=32), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('mode', sa.String(length=16), nullable=False),
        sa.Column('rubric_version_id', sa.String(length=36), nullable=False),
        sa.Column('snapshot_id', sa.String(length=36), nullable=True),
        sa.Column('actor', sa.String(length=128), nullable=False),
        sa.Column('steps', sa.JSON(), nullable=False),
        sa.Column('counts', sa.JSON(), nullable=False),
        sa.Column('error', sa.String(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['rubric_version_id'], ['rubric_version.id'], ),
        sa.ForeignKeyConstraint(['snapshot_id'], ['snapshot.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_run_rubric_version_id'), 'run', ['rubric_version_id'], unique=False)
    op.create_index(op.f('ix_run_snapshot_id'), 'run', ['snapshot_id'], unique=False)

    with op.batch_alter_table('proposal') as batch:
        batch.add_column(sa.Column('run_id', sa.String(length=36), nullable=True))
        batch.add_column(sa.Column('band_crossing', sa.Boolean(), nullable=True))
        batch.create_index(op.f('ix_proposal_run_id'), ['run_id'], unique=False)
        batch.create_foreign_key('fk_proposal_run_id', 'run', ['run_id'], ['id'])

    with op.batch_alter_table('confidence_event') as batch:
        batch.add_column(sa.Column('actor_role', sa.String(length=32), nullable=True))
        batch.add_column(sa.Column('reason_code', sa.String(length=64), nullable=True))
        batch.add_column(sa.Column('note', sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('confidence_event') as batch:
        batch.drop_column('note')
        batch.drop_column('reason_code')
        batch.drop_column('actor_role')

    with op.batch_alter_table('proposal') as batch:
        batch.drop_constraint('fk_proposal_run_id', type_='foreignkey')
        batch.drop_index(op.f('ix_proposal_run_id'))
        batch.drop_column('band_crossing')
        batch.drop_column('run_id')

    op.drop_index(op.f('ix_run_snapshot_id'), table_name='run')
    op.drop_index(op.f('ix_run_rubric_version_id'), table_name='run')
    op.drop_table('run')
