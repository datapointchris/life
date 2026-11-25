"""store each article url as the create cleans it

Revision ID: afbdd90516f2
Revises: be1a028874ff
Create Date: 2026-11-24 21:32:53.331508

The create strips tracking parameters and the fragment from a URL before it
looks the URL up. An article stored with them is never found by that lookup,
so a client's save under a `source_key` adds a second copy of it rather than
adopting it. Each stored URL is rewritten as `clean_url` writes it. Two articles
that would then share one URL stop the upgrade before any row changes.
"""

import sqlalchemy as sa
from alembic import op

from life.util import clean_url

# revision identifiers, used by Alembic.
revision = 'afbdd90516f2'
down_revision = 'be1a028874ff'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    stored = bind.execute(sa.text('SELECT id, url FROM articles WHERE url IS NOT NULL ORDER BY id')).all()
    ids_by_url: dict[str, list[int]] = {}
    for article_id, url in stored:
        ids_by_url.setdefault(clean_url(url), []).append(article_id)
    if shared := {url: ids for url, ids in ids_by_url.items() if len(ids) > 1}:
        named = '; '.join(f'articles {", ".join(map(str, ids))} all clean to {url}' for url, ids in shared.items())
        raise RuntimeError(f'{named}. Delete all but one article of each, then run the upgrade again.')
    for article_id, url in stored:
        if (cleaned := clean_url(url)) != url:
            bind.execute(sa.text('UPDATE articles SET url = :url WHERE id = :id'), {'url': cleaned, 'id': article_id})


def downgrade() -> None:
    # The revision below reads a cleaned URL as it reads any other, and a second upgrade finds nothing to clean.
    pass
