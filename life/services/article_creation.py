"""Save an article, or answer the one its `source_key` or URL already names.

`save_article` is the one create path. `POST /articles` calls it with a client's
body, and `save_article_from_url` calls it with the page's title, for
`POST /articles/create-from-url` and the bulk import worker. It raises domain
exceptions carrying the article it met, and each caller decides what one means:
the endpoint answers a status, the worker records the message.
"""

import datetime as dt
import hashlib
import json
from enum import StrEnum
from typing import Literal

import pendulum
import structlog
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from life import models
from life import schemas
from life.services.url_extraction import read_article_title
from life.util import clean_url

logger = structlog.get_logger()

# The create fields a version 1 fingerprint covers, each as the client sent it or as its default. A field
# joins, or a listed field's default changes, only under a new version: a stored fingerprint cannot be
# taken again, because nobody keeps the body it was taken from.
FINGERPRINT_V1_FIELDS = frozenset(
    {'title', 'url', 'tags', 'summary', 'notes', 'save_date', 'read_count', 'is_favorite', 'is_current', 'is_archived', 'review_days'}
)


class SaveOutcome(StrEnum):
    CREATED = 'created'
    REPEATED = 'repeated'
    ADOPTED = 'adopted'


class ArticleHeld(Exception):
    """A save met an article it may not change. `conflict` names what collided."""

    conflict: Literal['source_key', 'url']

    def __init__(self, held: models.Article, message: str):
        super().__init__(message)
        self.held = held


class ArticleAlreadyExists(ArticleHeld):
    """The URL is held under another key, or held at all when the save names no key."""

    conflict = 'url'

    def __init__(self, held: models.Article):
        under = f' under source_key {held.source_key!r}' if held.source_key is not None else ''
        super().__init__(held, f'article {held.id} already holds {held.url}{under}')


class SourceKeyHeld(ArticleHeld):
    """The key names an article saved from a different body."""

    conflict = 'source_key'

    def __init__(self, held: models.Article):
        super().__init__(held, f'article {held.id} holds source_key {held.source_key!r} from a different body, and was left as it is')


class SavedConcurrently(Exception):
    """Another save took the key or the URL between this save's reads and its write."""


def body_fingerprint(article: schemas.ArticleCreate) -> str:
    """The body's version 1 fingerprint: the URL as sent and the save date in UTC, so no release's cleaning changes it."""
    body = article.model_dump(mode='json', include=set(FINGERPRINT_V1_FIELDS))
    body['save_date'] = article.save_date.astimezone(dt.UTC).isoformat()
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return f'v1:{digest}'


def save_article(article: schemas.ArticleCreate, session: Session) -> tuple[models.Article, SaveOutcome]:
    """Save `article`, or answer the article its `source_key` or URL already names.

    A repeat of the body that saved a key answers that article, and another
    body raises `SourceKeyHeld`. A URL held under no key is adopted by a body
    naming one. The article takes the key and keeps every field of its own,
    since a person may have written them. A held URL raises
    `ArticleAlreadyExists` otherwise. Deleting an article frees its key, so a
    later save under that key adds the article again.
    """
    try:
        return save_or_answer_held(article, session)
    except IntegrityError, SavedConcurrently:
        # The other save has committed, so reading again finds what it saved.
        session.rollback()
        return save_or_answer_held(article, session)


def save_or_answer_held(article: schemas.ArticleCreate, session: Session) -> tuple[models.Article, SaveOutcome]:
    key = article.source_key
    url = clean_url(article.url)
    fingerprint = body_fingerprint(article) if key is not None else None
    if key is not None and (held := session.scalar(select(models.Article).where(models.Article.source_key == key))):
        if held.source_body_fingerprint != fingerprint:
            raise SourceKeyHeld(held)
        return held, SaveOutcome.REPEATED
    if held := session.scalar(select(models.Article).where(models.Article.url == url)):
        if key is None or held.source_key is not None:
            raise ArticleAlreadyExists(held)
        adopt(held, key, fingerprint, session)
        return held, SaveOutcome.ADOPTED
    saved = models.Article(**article.model_dump() | {'url': url}, source_body_fingerprint=fingerprint)
    session.add(saved)
    session.commit()
    session.refresh(saved)
    logger.info('article_saved', article_id=saved.id, source_key=key)
    return saved, SaveOutcome.CREATED


def adopt(held: models.Article, key: str, fingerprint: str | None, session: Session) -> None:
    """Give `held` the key only while it has none, so of two saves adopting one article the second reads it again."""
    taken = session.scalar(
        update(models.Article)
        .where(models.Article.id == held.id, models.Article.source_key.is_(None))
        .values(source_key=key, source_body_fingerprint=fingerprint)
        .returning(models.Article.id)
        .execution_options(synchronize_session=False)
    )
    if taken is None:
        raise SavedConcurrently
    session.commit()
    session.refresh(held)
    logger.info('article_adopted', article_id=held.id, source_key=key)


def save_article_from_url(url: str, notes: str | None, session: Session) -> models.Article:
    """Save the page at `url` under its own title, with no summary and no tags."""
    url = clean_url(url)
    # A held URL is refused before the page is fetched, since it would be refused after.
    if held := session.scalar(select(models.Article).where(models.Article.url == url)):
        raise ArticleAlreadyExists(held)
    title = read_article_title(url)
    article, _ = save_article(schemas.ArticleCreate(title=title, url=url, notes=notes, save_date=pendulum.now()), session)
    logger.info('article_created_from_url', url=url, title=article.title)
    return article
