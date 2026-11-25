"""add a client's source_key to articles

Revision ID: be1a028874ff
Revises: bec8078e4792
Create Date: 2026-11-24 20:46:33.193113

A client that saves articles on its own schedule names each by a key of its
own, so a repeated save finds the article rather than adding a second.
`source_body_sha256` fingerprints the body that saved or adopted it, which is
what a repeat is compared against. Every existing article keeps both null.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'be1a028874ff'
down_revision = 'bec8078e4792'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('articles', sa.Column('source_key', sa.Text(), nullable=True))
    op.add_column('articles', sa.Column('source_body_sha256', sa.Text(), nullable=True))
    op.create_unique_constraint(op.f('uq_articles_source_key'), 'articles', ['source_key'])


def downgrade() -> None:
    op.drop_constraint(op.f('uq_articles_source_key'), 'articles', type_='unique')
    op.drop_column('articles', 'source_body_sha256')
    op.drop_column('articles', 'source_key')
