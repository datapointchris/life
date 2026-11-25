import datetime as dt
from typing import ClassVar

from pydantic import AwareDatetime
from pydantic import BaseModel
from pydantic import ConfigDict

from life import models
from life.schemas.one_line_text import OneLineText
from life.schemas.partial_update import PartialUpdate


class ArticleConfig(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ArticleCreate(ArticleConfig):
    title: OneLineText
    url: str
    tags: list[str] = []
    summary: str
    notes: str | None = None
    save_date: AwareDatetime
    read_count: int = 0
    is_favorite: bool = False
    is_current: bool = False
    is_archived: bool = False
    review_days: int | None = None


class ArticleCreateFromUrl(ArticleConfig):
    url: str
    notes: str | None = None


class ArticleUrl(ArticleConfig):
    url: str


class ArticleBulkImport(ArticleConfig):
    urls: list[str] = []
    notes: dict[str, str] = {}


class Article(ArticleConfig):
    id: int
    title: str
    url: str
    tags: list[str]
    summary: str | None = None
    notes: str | None = None
    save_date: dt.datetime
    last_read_date: dt.datetime | None = None
    read_count: int
    is_favorite: bool
    is_current: bool
    is_archived: bool
    review_days: int | None = None


class ArticleUpdate(ArticleConfig, PartialUpdate):
    updates = models.Article
    # The column takes a null so this release reads one, and no client writes one until the release after it.
    refuses_null: ClassVar[frozenset[str]] = frozenset({'summary'})

    title: OneLineText | None = None
    tags: list[str] = []
    summary: str | None = None
    notes: str | None = None
    is_favorite: bool | None = None
    is_current: bool | None = None
    is_archived: bool | None = None
    last_read_date: AwareDatetime | None = None
    read_count: int | None = None
    review_days: int | None = None


class ArticleSummary(ArticleConfig):
    title: str
    summary: str
    tags: list[str]


class ArticleSummaryAndTags(ArticleConfig):
    """What Claude writes for a page. The title comes from the page, not the model."""

    summary: str
    tags: list[str]
