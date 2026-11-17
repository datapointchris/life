import datetime as dt

from pydantic import BaseModel
from pydantic import ConfigDict

from life import models
from life.iana_zone import IanaZone
from life.schemas.partial_update import PartialUpdate
from life.schemas.wall_clock import WallClock


class EventConfig(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class EventCreate(EventConfig):
    name: str
    date: WallClock
    timezone: IanaZone = 'UTC'
    venue: str
    url: str | None = None
    cost: float
    attending: bool
    notes: str | None = None


class Event(EventConfig):
    id: int
    name: str
    date: dt.datetime
    timezone: str
    venue: str
    url: str | None = None
    cost: float
    attending: bool
    notes: str | None = None


class EventUpdate(EventConfig, PartialUpdate):
    updates = models.Event

    name: str | None = None
    date: WallClock | None = None
    timezone: IanaZone | None = None
    venue: str | None = None
    url: str | None = None
    cost: float | None = None
    attending: bool | None = None
    notes: str | None = None
