"""A PATCH body over one model: every field may be omitted, and a field over a NOT NULL column is never nulled.

A subclass names its model in `updates`, and the NOT NULL columns are read from that model, so a
new schema or a new column is covered without anyone listing it. An omitted field stays at a
default Pydantic does not validate, so `model_dump(exclude_unset=True)` drops it and the column is
left alone. An explicit null is validated and refused with a 422 naming the field, where it would
otherwise reach the column and come back as a 500.
"""

from typing import Any
from typing import ClassVar

from pydantic import BaseModel
from pydantic import ValidationInfo
from pydantic import field_validator

from life.database.base import Base


class PartialUpdate(BaseModel):
    updates: ClassVar[type[Base]]
    not_null: ClassVar[frozenset[str]] = frozenset()

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        super().__pydantic_init_subclass__(**kwargs)
        cls.not_null = frozenset(
            attr.key for attr in cls.updates.__mapper__.column_attrs if attr.key in cls.model_fields and not attr.columns[0].nullable
        )

    @field_validator('*')
    @classmethod
    def refuse_null(cls, value: Any, info: ValidationInfo) -> Any:
        if value is None and info.field_name in cls.not_null:
            raise ValueError('cannot be null; omit the field to leave it unchanged')
        return value
