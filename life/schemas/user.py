import datetime as dt
from typing import Any

from pydantic import AwareDatetime
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import field_validator

from life import models
from life.schemas.partial_update import PartialUpdate


class UserConfig(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserCreate(UserConfig):
    name: str
    email: str
    password: str

    @field_validator('name', 'email', 'password')
    @classmethod
    def check_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError('Field cannot be empty')
        return v


class User(UserConfig):
    id: int
    alternative_id: int
    name: str
    email: str
    is_admin: bool
    created_on: dt.datetime
    last_login: dt.datetime | None
    preferences: Any


class UserUpdate(UserConfig, PartialUpdate):
    updates = models.User

    name: str | None = None
    email: str | None = None
    password: str | None = None
    is_admin: bool | None = None
    last_login: AwareDatetime | None = None
    preferences: Any | None = None
