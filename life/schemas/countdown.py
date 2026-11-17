import datetime as dt

from pydantic import BaseModel
from pydantic import ConfigDict

from life import models
from life.schemas.partial_update import PartialUpdate


class CountdownConfig(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CountdownCreate(CountdownConfig):
    name: str
    notes: str | None = None
    due_date: dt.date


class Countdown(CountdownConfig):
    id: int
    name: str
    notes: str | None = None
    due_date: dt.date


class CountdownUpdate(CountdownConfig, PartialUpdate):
    updates = models.Countdown

    name: str | None = None
    notes: str | None = None
    due_date: dt.date | None = None
