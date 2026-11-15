"""add habit checklist items and item ticks

Revision ID: c9e8ce017a42
Revises: bb7c7a9de024
Create Date: 2026-11-14 20:50:05.239712

A habit's checklist items are what its day asks for, each done a target number
of times, and an item tick is one time one was done. Both tables are new, so the
release that carries them needs nothing of the serving color.
"""

import sqlalchemy as sa
from alembic import op

revision = 'c9e8ce017a42'
down_revision = 'bb7c7a9de024'
branch_labels = None
depends_on = None

AUDITED = ('checklist_items', 'item_ticks')


def upgrade() -> None:
    op.create_table(
        'checklist_items',
        sa.Column('id', sa.Integer(), sa.Identity(always=True), nullable=False),
        sa.Column('habit_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('daily_target', sa.Integer(), nullable=False),
        sa.CheckConstraint('daily_target >= 1', name=op.f('ck_checklist_items_daily_target_positive')),
        sa.ForeignKeyConstraint(['habit_id'], ['habits.habits.id'], name=op.f('fk_checklist_items_habit_id_habits'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_checklist_items')),
        schema='habits',
    )
    op.create_index(op.f('ix_habits_checklist_items_habit_id'), 'checklist_items', ['habit_id'], schema='habits')

    op.create_table(
        'item_ticks',
        sa.Column('id', sa.Integer(), sa.Identity(always=True), nullable=False),
        sa.Column('item_id', sa.Integer(), nullable=True),
        sa.Column('habit_id', sa.Integer(), nullable=True),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('tick_date', sa.Date(), nullable=False),
        sa.Column('ticked_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(
            ['item_id'], ['habits.checklist_items.id'], name=op.f('fk_item_ticks_item_id_checklist_items'), ondelete='SET NULL'
        ),
        sa.ForeignKeyConstraint(['habit_id'], ['habits.habits.id'], name=op.f('fk_item_ticks_habit_id_habits'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_item_ticks')),
        schema='habits',
    )
    op.create_index(op.f('ix_habits_item_ticks_habit_id'), 'item_ticks', ['habit_id'], schema='habits')
    op.create_index('ix_habits_item_ticks_item_id_tick_date', 'item_ticks', ['item_id', 'tick_date'], schema='habits')

    for table in AUDITED:
        op.execute(
            f'CREATE TRIGGER life_audit_trail AFTER INSERT OR UPDATE OR DELETE ON "habits"."{table}" '
            'FOR EACH ROW EXECUTE FUNCTION life_audit_trail_record()'
        )


def downgrade() -> None:
    op.drop_table('item_ticks', schema='habits')
    op.drop_table('checklist_items', schema='habits')
