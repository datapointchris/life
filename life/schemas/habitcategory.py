from pydantic import BaseModel
from pydantic import ConfigDict

from life import models
from life.schemas.partial_update import PartialUpdate


class HabitConfig(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=True)


class HabitCategory(HabitConfig):
    id: int
    name: str
    is_current: bool


class HabitCategoryCreate(HabitConfig):
    name: str
    is_current: bool = True


class HabitCategoryUpdate(HabitConfig, PartialUpdate):
    updates = models.HabitCategory

    name: str | None = None
    is_current: bool | None = None
