"""an article needs no summary

Revision ID: bec8078e4792
Revises: 2cf648a5eded
Create Date: 2026-11-24 20:26:08.307667

An article's summary is optional.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'bec8078e4792'
down_revision = '2cf648a5eded'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column('articles', 'summary', existing_type=sa.Text(), nullable=True)


def downgrade() -> None:
    # The revision below requires a summary on every article, and nothing can write one back.
    missing = op.get_bind().scalar(sa.text('SELECT count(*) FROM articles WHERE summary IS NULL'))
    if missing:
        raise NotImplementedError(
            f'{missing} articles have no summary, which the schema before bec8078e4792 cannot hold. '
            'Write a summary on each or delete it, or restore from a database backup taken before this revision ran.'
        )
    op.alter_column('articles', 'summary', existing_type=sa.Text(), nullable=False)
