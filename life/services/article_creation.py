"""Save an article from its URL: read the page for its title, and persist it.

Used by `POST /articles/create-from-url` and the bulk import worker, which the
endpoint module also enqueues into. Both import this module, so neither has to
import the other. Reading the page refuses a bot check or a redirect to the
homepage, which would otherwise be saved under that page's title.
"""

import pendulum
import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from life import models
from life.services.url_extraction import read_article_page
from life.util import clean_url

logger = structlog.get_logger()


class ArticleAlreadyExists(Exception):
    """An article with this URL is already saved."""

    def __init__(self, url: str):
        super().__init__(f'Article already exists: {url}')
        self.url = url


def save_article_from_url(url: str, notes: str | None, session: Session) -> models.Article:
    """Save the page at `url` under its own title, with no summary and no tags.

    It raises domain exceptions and each caller decides what one means: the
    endpoint answers a status, the worker records the message.
    """
    url = clean_url(url)
    existing = session.scalar(select(models.Article).where(models.Article.url == url))
    if existing:
        raise ArticleAlreadyExists(url)

    page = read_article_page(url)

    article = models.Article(
        title=page.title,
        url=url,
        tags=[],
        notes=notes,
        save_date=pendulum.now(),
        read_count=0,
        is_favorite=False,
        is_current=False,
        is_archived=False,
    )
    session.add(article)
    session.commit()
    session.refresh(article)
    logger.info('article_created_from_url', url=url, title=page.title)
    return article
