"""A habit's checklist on one day, and the completion its ticks decide.

A habit with checklist items completes itself. The tick that brings every item
to its target records the habit's completion for that day, and the untick that
takes one back below its target removes it. Adding, editing or removing an item
does the same for today. Only crossing the line acts, so a completion recorded
by hand stays put while the ticks never reached the targets.
"""

import datetime as dt
from collections import defaultdict
from collections.abc import Sequence

from sqlalchemy import delete
from sqlalchemy import select
from sqlalchemy.orm import Session

from life import models
from life import schemas


def items_by_habit(session: Session, habit_ids: Sequence[int]) -> dict[int, list[models.HabitChecklistItem]]:
    query = (
        select(models.HabitChecklistItem).where(models.HabitChecklistItem.habit_id.in_(habit_ids)).order_by(models.HabitChecklistItem.id)
    )
    grouped: dict[int, list[models.HabitChecklistItem]] = defaultdict(list)
    for item in session.scalars(query):
        grouped[item.habit_id].append(item)
    return grouped


def ticks_by_item(session: Session, item_ids: Sequence[int], day: dt.date) -> dict[int, list[models.HabitItemTick]]:
    query = (
        select(models.HabitItemTick)
        .where(models.HabitItemTick.item_id.in_(item_ids), models.HabitItemTick.tick_date == day)
        .order_by(models.HabitItemTick.ticked_at, models.HabitItemTick.id)
    )
    grouped: dict[int, list[models.HabitItemTick]] = defaultdict(list)
    for tick in session.scalars(query):
        if tick.item_id is not None:
            grouped[tick.item_id].append(tick)
    return grouped


def checklists(session: Session, habits: Sequence[models.Habit], day: dt.date) -> list[schemas.HabitChecklist]:
    """The checklist of each habit in `habits` that has items, in the order given."""
    items = items_by_habit(session, [h.id for h in habits])
    ticks = ticks_by_item(session, [i.id for group in items.values() for i in group], day)
    built = []
    for habit in habits:
        if not items.get(habit.id):
            continue
        rows = [
            schemas.HabitChecklistItemDay(
                id=item.id,
                name=item.name,
                daily_target=item.daily_target,
                ticks=[schemas.HabitItemTick.model_validate(t) for t in ticks.get(item.id, [])],
                done=len(ticks.get(item.id, [])) >= item.daily_target,
            )
            for item in items[habit.id]
        ]
        built.append(schemas.HabitChecklist(habit_id=habit.id, name=habit.name, date=day, items=rows, complete=all(r.done for r in rows)))
    return built


def checklist(session: Session, habit: models.Habit, day: dt.date) -> schemas.HabitChecklist:
    """One habit's checklist; a habit with no items has an empty, incomplete one."""
    found = checklists(session, [habit], day)
    return found[0] if found else schemas.HabitChecklist(habit_id=habit.id, name=habit.name, date=day, items=[], complete=False)


def completions_on(session: Session, habit: models.Habit, day: dt.date) -> list[models.HabitCompleted]:
    query = select(models.HabitCompleted).where(models.HabitCompleted.habit_id == habit.id, models.HabitCompleted.complete_date == day)
    return list(session.scalars(query))


def settle(session: Session, habit: models.Habit, day: dt.date, was_complete: bool) -> schemas.HabitChecklist:
    """Record or remove the day's completion when a change carried the checklist across its line, then commit.

    A habit left with no items is not decided by a checklist, so its completion stays as it is.
    """
    session.flush()
    after = checklist(session, habit, day)
    if after.items and after.complete and not was_complete and not completions_on(session, habit, day):
        session.add(models.HabitCompleted(habit_id=habit.id, name=habit.name, category_id=habit.category_id, complete_date=day))
    if after.items and was_complete and not after.complete:
        session.execute(
            delete(models.HabitCompleted).where(models.HabitCompleted.habit_id == habit.id, models.HabitCompleted.complete_date == day)
        )
    session.commit()
    return after


def tick(session: Session, item: models.HabitChecklistItem, day: dt.date) -> schemas.HabitChecklist:
    habit = session.get_one(models.Habit, item.habit_id)
    was_complete = checklist(session, habit, day).complete
    session.add(models.HabitItemTick(item_id=item.id, habit_id=habit.id, name=item.name, tick_date=day))
    return settle(session, habit, day, was_complete)


def untick(session: Session, item: models.HabitChecklistItem, recorded: models.HabitItemTick) -> schemas.HabitChecklist:
    habit = session.get_one(models.Habit, item.habit_id)
    day = recorded.tick_date
    was_complete = checklist(session, habit, day).complete
    session.delete(recorded)
    return settle(session, habit, day, was_complete)


# An item change redefines done from now on, so it settles today and leaves past days' completions as history.


def add_item(session: Session, habit: models.Habit, fields: schemas.HabitChecklistItemCreate, today: dt.date) -> models.HabitChecklistItem:
    was_complete = checklist(session, habit, today).complete
    item = models.HabitChecklistItem(habit_id=habit.id, **fields.model_dump())
    session.add(item)
    settle(session, habit, today, was_complete)
    session.refresh(item)
    return item


def change_item(
    session: Session, item: models.HabitChecklistItem, changes: schemas.HabitChecklistItemUpdate, today: dt.date
) -> models.HabitChecklistItem:
    habit = session.get_one(models.Habit, item.habit_id)
    was_complete = checklist(session, habit, today).complete
    for attr, value in changes.model_dump(exclude_unset=True).items():
        setattr(item, attr, value)
    settle(session, habit, today, was_complete)
    session.refresh(item)
    return item


def remove_item(session: Session, item: models.HabitChecklistItem, today: dt.date) -> None:
    habit = session.get_one(models.Habit, item.habit_id)
    was_complete = checklist(session, habit, today).complete
    session.delete(item)
    settle(session, habit, today, was_complete)
