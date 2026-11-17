import datetime as dt

from pydantic import AwareDatetime
from pydantic import BaseModel
from pydantic import ConfigDict

from life import models
from life.schemas.partial_update import PartialUpdate


class PatternConfig(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class PatternCreate(PatternConfig):
    message: str
    # Optional so a capture is one argument, but settable so the dotfiles JSONL
    # entries import at the time they were written rather than the time of import.
    recorded_at: AwareDatetime | None = None


class Pattern(PatternConfig):
    id: int
    message: str
    recorded_at: dt.datetime


class PatternUpdate(PatternConfig, PartialUpdate):
    updates = models.Pattern

    message: str | None = None
    recorded_at: AwareDatetime | None = None
