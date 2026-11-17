from pydantic import BaseModel
from pydantic import ConfigDict

from life import models
from life.schemas.boxitem import BoxItem
from life.schemas.partial_update import PartialUpdate


class BoxConfig(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class BoxCreate(BoxConfig):
    name: str
    number: int
    size: str
    essential: bool
    warm: bool
    liquid: bool


class Box(BoxConfig):
    id: int
    number: int | None
    name: str
    size: str
    essential: bool
    warm: bool
    liquid: bool
    items: list[BoxItem]

    @property
    def item_count(self):
        return len(self.items)


class BoxUpdate(BoxConfig, PartialUpdate):
    updates = models.Box

    name: str | None = None
    number: int | None = None
    size: str | None = None
    essential: bool | None = None
    warm: bool | None = None
    liquid: bool | None = None
