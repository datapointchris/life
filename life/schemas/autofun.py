import datetime as dt

from pydantic import BaseModel
from pydantic import ConfigDict

from life import models
from life.schemas.partial_update import PartialUpdate


class AutoFunConfig(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class AutoFunCreate(AutoFunConfig):
    name: str
    notes: str | None = None


class AutoFun(AutoFunConfig):
    id: int
    name: str
    notes: str | None = None
    is_completed: bool
    completed_date: dt.datetime | None = None
    added_date: dt.datetime


class AutoFunUpdate(AutoFunConfig, PartialUpdate):
    updates = models.AutoFun

    name: str | None = None
    notes: str | None = None
