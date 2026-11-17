import datetime as dt

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import PositiveInt
from pydantic import field_validator

from life import models
from life.schemas.habitcompleted import EASTERNMOST_UTC_OFFSET
from life.schemas.partial_update import PartialUpdate


class ChecklistConfig(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class HabitChecklistItemCreate(ChecklistConfig):
    name: str
    daily_target: PositiveInt


class HabitChecklistItemUpdate(ChecklistConfig, PartialUpdate):
    updates = models.HabitChecklistItem

    name: str | None = None
    daily_target: PositiveInt | None = None


class HabitChecklistItem(ChecklistConfig):
    id: int
    habit_id: int
    name: str
    daily_target: int


class HabitItemTickCreate(ChecklistConfig):
    """`tick_date` left off is today in the request's zone."""

    tick_date: dt.date | None = None

    @field_validator('tick_date')
    @classmethod
    def tick_date_has_started_somewhere(cls, v: dt.date | None) -> dt.date | None:
        """The same bound a completion has: the latest today anywhere, UTC+14."""
        if v is not None and v > (dt.datetime.now(dt.UTC) + EASTERNMOST_UTC_OFFSET).date():
            raise ValueError('tick_date is in the future')
        return v


class HabitItemTick(ChecklistConfig):
    id: int
    item_id: int | None
    habit_id: int | None
    name: str
    tick_date: dt.date
    ticked_at: dt.datetime


class HabitChecklistItemDay(ChecklistConfig):
    """One item on one day: its ticks, oldest first, and whether they reach its target."""

    id: int
    name: str
    daily_target: int
    ticks: list[HabitItemTick]
    done: bool


class HabitChecklist(ChecklistConfig):
    """A habit's checklist on one day.

    `complete` says every item reached its target. Whether the habit itself is
    done that day is the board's `completed`, which a completion recorded by hand
    also reaches.
    """

    habit_id: int
    name: str
    date: dt.date
    items: list[HabitChecklistItemDay]
    complete: bool
