import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from life import models


def test_a_job_write_is_audited_under_its_name_and_never_copies_a_password(txn_api):
    _, session = txn_api
    with structlog.contextvars.bound_contextvars(job_name='make_report', job_run_id='run-1'):
        job_session = Session(bind=session.connection(), join_transaction_mode='create_savepoint')
        user = models.User(name='audited', email='audited@example.com', password='hashed-secret')
        job_session.add(user)
        job_session.flush()
        user_id = str(user.id)
        job_session.delete(user)
        job_session.flush()

    entries = job_session.scalars(
        select(models.RecordChange)
        .where(models.RecordChange.table_name == 'users', models.RecordChange.record_id == user_id)
        .order_by(models.RecordChange.id)
    ).all()
    assert [entry.operation for entry in entries] == ['insert', 'delete']
    assert {(entry.actor, entry.job_run_id) for entry in entries} == {('scheduler/make_report', 'run-1')}
    assert entries[0].changes['email'] == {'new': 'audited@example.com'}
    assert entries[1].changes['email'] == {'old': 'audited@example.com'}
    assert not any('password' in entry.changes for entry in entries)
