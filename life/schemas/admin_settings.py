from pydantic import BaseModel
from pydantic import ConfigDict

from life import models
from life.schemas.partial_update import PartialUpdate


class AdminSettingsConfig(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class AdminSettings(AdminSettingsConfig):
    is_signup_open: bool


class AdminSettingsUpdate(AdminSettingsConfig, PartialUpdate):
    updates = models.AdminSettings

    is_signup_open: bool | None = None
