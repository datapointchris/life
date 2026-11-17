# The life audit trail

Every insert, update and delete to a row of a life table leaves one entry in `life_audit_trail`.
The entry names the table and the row's primary key. It holds each written column's old and new
value, and who wrote it. `GET /api/v1/admin/record-changes` reads it, filtered by table, row,
writer and time window.

## A trigger on each table writes the entry, so no write path is missed

The function `life_audit_trail_record()` runs after every row a table's trigger sees. That covers
the ORM, a Core `update()` or `delete()`, raw SQL, and an `ON DELETE SET NULL` or `CASCADE` that
Postgres applies itself. An application-side listener sees only what the ORM flushes, and a
foreign-key action changes rows the ORM never loaded.

A table's trigger is attached at the end of the migration run that creates the table, from its
declaration below, so no migration writes one.

A dropped table's entries stay. A drop fires no row trigger, so the trail records nothing for it,
and `record-changes` still reads the table's history by name.

The logs do not replace the trail. They are kept for a fixed retention period, and a log line or
span records that a request ran, never which values it changed. Each entry carries the
`request_id` or `job_run_id` of the write, which joins it to the logs while they last.

## Who wrote it comes from the session's transaction

The trigger reads three transaction-local settings: `life.actor`, `life.request_id` and
`life.job_run_id`. An `after_begin` listener in `life/models/record_change.py` sets them
whenever a session begins a transaction, so they end with it.

- **A person** is recorded by the user's email. `authenticated_user` binds it to the request's
  session.
- **A service client** is recorded by its client id. `get_scoped_client` binds it.
- **A scheduler job** is recorded as `scheduler/<job_name>`. The job wrapper binds `job_name` and
  `job_run_id` into structlog's context, and the listener reads them there.
- **A bulk article import** is recorded by the user who queued it. The queue item carries the
  email and the request id, and the worker binds both.

A session with none of these bound records no writer.

The `life` CLI logs in as its user, so anything driving the CLI under that login is recorded as
that user. Only a service client is told apart from the person.

## A secret column opts out of the trail

Every column is recorded unless it opts out. A column opts out with
`info={'record_changes': False}`, and a table opts out with the same key in its `__table_args__`
info. `users.password` opts out. So do `scheduler_job_runs`, which is itself a record of what ran,
and the trail itself. `apscheduler_jobs`, which APScheduler creates and no model describes, opts
out through a row its migration wrote.

The declarations live in `life_audit_trail_tables`, one row per table, which the trigger reads to
know which columns to strip. Once a migration run reaches head, `declare_audit_trail` writes each
model's row, and `life_audit_trail_reconcile()` attaches the trigger to every table recorded and
drops it from every table that opts out. A table with no row is recorded whole, so a new table is
audited without its migration doing anything. The reconcile refuses the run where a recorded table
records a column named like a credential. `SELECT * FROM life_audit_trail_targets` shows each
table's declaration beside whether its trigger is attached.

The trigger function runs as its owner. A role named for the database with `_app` after it, where
one exists, reads the trail and cannot write it.
