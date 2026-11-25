import datetime as dt
from typing import Literal

from pydantic import AwareDatetime
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from life import models
from life.schemas.one_line_text import OneLineText
from life.schemas.partial_update import PartialUpdate


class ArticleConfig(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ArticleCreate(ArticleConfig):
    title: OneLineText
    url: str
    tags: list[str] = []
    summary: str | None = None
    notes: str | None = None
    save_date: AwareDatetime
    read_count: int = 0
    is_favorite: bool = False
    is_current: bool = False
    is_archived: bool = False
    review_days: int | None = None
    # A client's own name for the article, which makes the create safe to repeat.
    source_key: str | None = Field(default=None, min_length=1)


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
    source_key: str | None = None


class ArticleSaved(Article):
    """What a create answers: `adopted` is true only on the create that gave an article saved by hand its `source_key`."""

    adopted: bool = False


class ArticleConflict(BaseModel):
    """A create's 409: `conflict` names what collided, `source_key` when the key holds another body and `url` when the URL is held."""

    error: str
    message: str
    conflict: Literal['source_key', 'url']
    article_id: int
    source_key: str | None


class ArticleUpdate(ArticleConfig, PartialUpdate):
    updates = models.Article

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
