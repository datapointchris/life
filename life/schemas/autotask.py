import datetime as dt

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from life import models
from life.schemas.partial_update import PartialUpdate
from life.schemas.task import WindowDays


class AutoTaskConfig(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class AutoTaskCreate(AutoTaskConfig):
    name: str
    notes: str | None = None
    category: str
    frequency: str
    window_days: WindowDays | None = Field(
        None, description="Days each copy gets before it sorts as due. The category's window when omitted."
    )
    anchor: str = 'completion'
    max_concurrent: int | None = None


class AutoTask(AutoTaskConfig):
    id: int
    name: str
    category: str
    notes: str | None = None
    frequency: str
    window_days: int | None = None
    anchor: str
    max_concurrent: int
    first_run_date: dt.datetime
    last_run_date: dt.datetime
    run_count: int


class AutoTaskUpdate(AutoTaskConfig, PartialUpdate):
    updates = models.AutoTask

    name: str | None = None
    category: str | None = None
    notes: str | None = None
    frequency: str | None = None
    window_days: WindowDays | None = None
    anchor: str | None = None
    max_concurrent: int | None = None
