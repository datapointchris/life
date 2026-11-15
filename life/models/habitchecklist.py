import datetime as dt

from sqlalchemy import CheckConstraint
from sqlalchemy import Date
from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy import Identity
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import Text
from sqlalchemy import func
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column

from life.database.base import Base


class HabitChecklistItem(Base):
    """One thing a habit's day asks for, done `daily_target` times.

    A habit with items completes itself: the tick that brings every item to its
    target records the habit's completion for that day.
    """

    __tablename__ = 'checklist_items'
    __table_args__ = (
        CheckConstraint('daily_target >= 1', name='daily_target_positive'),
        {'schema': 'habits'},
    )
    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    habit_id: Mapped[int] = mapped_column(Integer, ForeignKey('habits.habits.id', ondelete='CASCADE'), nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    daily_target: Mapped[int] = mapped_column(Integer, nullable=False)

    def __repr__(self):
        return f'HabitChecklistItem(habit_id={self.habit_id!r}, name={self.name!r}, daily_target={self.daily_target!r})'


class HabitItemTick(Base):
    """One time an item was done, such as one set of push-ups.

    A historical fact like a completion, so the item's name is kept on the row and
    both links fall to null rather than taking the row with them when the item or
    its habit is deleted.
    """

    __tablename__ = 'item_ticks'
    __table_args__ = (
        Index('ix_habits_item_ticks_item_id_tick_date', 'item_id', 'tick_date'),
        {'schema': 'habits'},
    )
    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    item_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('habits.checklist_items.id', ondelete='SET NULL'), nullable=True)
    habit_id: Mapped[int | None] = mapped_column(Integer, ForeignKey('habits.habits.id', ondelete='SET NULL'), nullable=True, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    tick_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    ticked_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    def __repr__(self):
        return f'HabitItemTick(item_id={self.item_id!r}, name={self.name!r}, tick_date={self.tick_date!r})'
