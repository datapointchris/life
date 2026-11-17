"""narrow the app role on the audit trail at every reconcile

Revision ID: 2cf648a5eded
Revises: fbfcfb978cfb
Create Date: 2026-11-17 11:53:28.306254

fbfcfb978cfb revoked writes on the trail from `life_app` once, and only where the role already
existed. Production creates `life_app` later, from the deploy's role convergence, which grants it
DML on every table it holds nothing on, the trail included. So the reconcile, which runs at the end
of every migration run, takes the writes back each time.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = '2cf648a5eded'
down_revision = 'fbfcfb978cfb'
branch_labels = None
depends_on = None

RECONCILE_AND_NARROW = """
CREATE OR REPLACE FUNCTION life_audit_trail_reconcile() RETURNS void LANGUAGE plpgsql AS $$
DECLARE
    app_role text := current_database() || '_app';
    copied text;
    target life_audit_trail_targets;
BEGIN
    SELECT string_agg(format('%s.%I', t.audited_table, a.attname), ', ') INTO copied
    FROM life_audit_trail_targets AS t
    JOIN pg_attribute AS a ON a.attrelid = t.audited_table AND a.attnum > 0 AND NOT a.attisdropped
    WHERE t.is_recorded
        AND a.attname ~ '(^|_)(password|secret|token|api_key)$'
        AND a.attname <> ALL (t.ignored_columns);
    IF copied IS NOT NULL THEN
        RAISE EXCEPTION 'the audit trail would copy %; list each in its table''s ignored_columns', copied;
    END IF;

    FOR target IN SELECT * FROM life_audit_trail_targets WHERE is_recorded <> is_attached LOOP
        IF target.is_recorded THEN
            EXECUTE format('CREATE TRIGGER life_audit_trail AFTER INSERT OR UPDATE OR DELETE ON %s '
                           'FOR EACH ROW EXECUTE FUNCTION life_audit_trail_record()', target.audited_table);
        ELSE
            EXECUTE format('DROP TRIGGER life_audit_trail ON %s', target.audited_table);
        END IF;
    END LOOP;

    IF EXISTS (SELECT FROM pg_roles WHERE rolname = app_role) THEN
        EXECUTE format('REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON life_audit_trail, life_audit_trail_tables FROM %I', app_role);
        EXECUTE format('GRANT SELECT ON life_audit_trail, life_audit_trail_tables TO %I', app_role);
    END IF;
END;
$$;
"""

RECONCILE_ONLY = """
CREATE OR REPLACE FUNCTION life_audit_trail_reconcile() RETURNS void LANGUAGE plpgsql AS $$
DECLARE
    copied text;
    target life_audit_trail_targets;
BEGIN
    SELECT string_agg(format('%s.%I', t.audited_table, a.attname), ', ') INTO copied
    FROM life_audit_trail_targets AS t
    JOIN pg_attribute AS a ON a.attrelid = t.audited_table AND a.attnum > 0 AND NOT a.attisdropped
    WHERE t.is_recorded
        AND a.attname ~ '(^|_)(password|secret|token|api_key)$'
        AND a.attname <> ALL (t.ignored_columns);
    IF copied IS NOT NULL THEN
        RAISE EXCEPTION 'the audit trail would copy %; list each in its table''s ignored_columns', copied;
    END IF;

    FOR target IN SELECT * FROM life_audit_trail_targets WHERE is_recorded <> is_attached LOOP
        IF target.is_recorded THEN
            EXECUTE format('CREATE TRIGGER life_audit_trail AFTER INSERT OR UPDATE OR DELETE ON %s '
                           'FOR EACH ROW EXECUTE FUNCTION life_audit_trail_record()', target.audited_table);
        ELSE
            EXECUTE format('DROP TRIGGER life_audit_trail ON %s', target.audited_table);
        END IF;
    END LOOP;
END;
$$;
"""


def upgrade() -> None:
    op.execute(RECONCILE_AND_NARROW)


def downgrade() -> None:
    op.execute(RECONCILE_ONLY)
