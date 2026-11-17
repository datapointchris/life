from pydantic import BaseModel
from pydantic import ConfigDict

from life import models
from life.schemas.habitcategory import HabitCategory
from life.schemas.partial_update import PartialUpdate


class HabitConfig(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


class HabitCreate(HabitConfig):
    name: str
    category_id: int
    is_current: bool = True


class Habit(HabitConfig):
    id: int
    name: str
    category_id: int
    category: HabitCategory
    is_current: bool


class HabitUpdate(HabitConfig, PartialUpdate):
    updates = models.Habit

    name: str | None = None
    category_id: int | None = None
    is_current: bool | None = None
