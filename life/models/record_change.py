"""Every write to a life table leaves a row in `life_audit_trail`, naming who made it.

A row trigger on each table writes the entry, so every path that reaches the database is audited:
the ORM, a Core statement, raw SQL, and an `ON DELETE` action Postgres takes itself. The trigger
reads who is writing from three transaction-local settings, which `name_the_writer` sets each time
a session begins a transaction. The API binds the signed-in user's email or the service client's
id to the session where it resolves the caller. A scheduler job is named by the `job_name` its
wrapper binds into structlog's context, which also carries `request_id` and `job_run_id`.

A table opts out with `'info': {'record_changes': False}` in its `__table_args__`, and a column
with the same key in its `info`. Once the migrations reach head, `declare_audit_trail` writes
those declarations into `life_audit_trail_tables`, and `life_audit_trail_reconcile()` attaches or
drops each table's trigger to match. So a migration creating a table writes no trigger of its own.
"""

import datetime as dt
from typing import Any

import structlog
from sqlalchemy import BigInteger
from sqlalchemy import Boolean
from sqlalchemy import CheckConstraint
from sqlalchemy import Connection
from sqlalchemy import DateTime
from sqlalchemy import Identity
from sqlalchemy import Index
from sqlalchemy import Text
from sqlalchemy import event
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import Session
from sqlalchemy.orm import SessionTransaction
from sqlalchemy.orm import mapped_column

from life.database.base import Base

RECORDED = 'record_changes'
ACTOR = 'record_changes_actor'


class RecordChange(Base):
    """One write to one row of any table, and who made it.

    `changes` maps each column the write touched to `{"old": ..., "new": ...}`. An insert carries no
    `old`, and a delete no `new`.
    """

    __tablename__ = 'life_audit_trail'
    __table_args__ = (
        CheckConstraint("operation IN ('insert', 'update', 'delete')", name='operation_is_a_write'),
        Index('idx_life_audit_trail_record', 'table_name', 'record_id', 'changed_at'),
        {'info': {RECORDED: False}},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    changed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    table_name: Mapped[str] = mapped_column(Text, nullable=False)
    record_id: Mapped[str] = mapped_column(Text, nullable=False)
    operation: Mapped[str] = mapped_column(Text, nullable=False)
    changes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    actor: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    request_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_run_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f'RecordChange({self.operation} {self.table_name}/{self.record_id} by {self.actor!r})'


def bind_actor(session: Session, actor: str) -> None:
    """Name who makes every write `session` sends from here on, including in the open transaction."""
    session.info[ACTOR] = actor
    if session.in_transaction():
        set_writer_settings(session, session.connection())


def set_writer_settings(session: Session, connection: Connection) -> None:
    bound = structlog.contextvars.get_contextvars()
    job_name = bound.get('job_name')
    actor = session.info.get(ACTOR) or (f'scheduler/{job_name}' if job_name else '')
    connection.execute(
        select(
            func.set_config('life.actor', actor, True),
            func.set_config('life.request_id', bound.get('request_id') or '', True),
            func.set_config('life.job_run_id', bound.get('job_run_id') or '', True),
        )
    )


@event.listens_for(Session, 'after_begin')
def name_the_writer(session: Session, _transaction: SessionTransaction, connection: Connection) -> None:
    """Tell the audit trigger who writes in this transaction. The settings end with it."""
    set_writer_settings(session, connection)


class AuditTrailTable(Base):
    """What the trail records of one table. A table with no row is recorded whole."""

    __tablename__ = 'life_audit_trail_tables'
    __table_args__ = ({'info': {RECORDED: False}},)

    table_schema: Mapped[str] = mapped_column(Text, primary_key=True)
    table_name: Mapped[str] = mapped_column(Text, primary_key=True)
    is_recorded: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text('true'))
    ignored_columns: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'"))


def declare_audit_trail(connection: Connection) -> None:
    """Write what each model declares about the trail, then have Postgres attach or drop each trigger to match."""
    declared = [
        {
            'table_schema': table.schema or 'public',
            'table_name': table.name,
            'is_recorded': table.info.get(RECORDED, True),
            'ignored_columns': sorted(column.name for column in table.columns if not column.info.get(RECORDED, True)),
        }
        for table in Base.metadata.sorted_tables
    ]
    statement = insert(AuditTrailTable).values(declared)
    connection.execute(
        statement.on_conflict_do_update(
            index_elements=[AuditTrailTable.table_schema, AuditTrailTable.table_name],
            set_={'is_recorded': statement.excluded.is_recorded, 'ignored_columns': statement.excluded.ignored_columns},
        )
    )
    connection.execute(select(func.life_audit_trail_reconcile()))
