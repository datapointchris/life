-- Brings the database's two login roles to what life declares, run as the server's superuser
-- before the migrations. The owner is named for the database: it owns every object and the
-- migrations log in as it. `<database>_app` is what the API and the scheduler log in as: it holds
-- DML on every table and usage on every sequence, now and on what the owner creates later, and no
-- DDL. A migration narrows it further, as the audit trail's reconcile does.
--
-- The caller binds each password as a setting first: life_roles.owner_password,
-- life_roles.app_password and, where the superuser's own changes, life_roles.superuser_password.
-- It is one statement, so a driver runs it with no psql in between.
DO $$
DECLARE
    owner_role text := current_database();
    app_role text := current_database() || '_app';
    superuser_password text := nullif(current_setting('life_roles.superuser_password', true), '');
    schema_name text;
    object_name text;
BEGIN
    IF owner_role = session_user THEN
        RAISE EXCEPTION 'run this as the server''s superuser, never as %, the role it narrows', owner_role;
    END IF;

    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = owner_role) THEN
        EXECUTE format('CREATE ROLE %I', owner_role);
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = app_role) THEN
        EXECUTE format('CREATE ROLE %I', app_role);
    END IF;
    EXECUTE format('ALTER ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L',
                   owner_role, current_setting('life_roles.owner_password'));
    EXECUTE format('ALTER ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L',
                   app_role, current_setting('life_roles.app_password'));
    IF superuser_password IS NOT NULL THEN
        EXECUTE format('ALTER ROLE %I PASSWORD %L', session_user, superuser_password);
    END IF;

    EXECUTE format('ALTER DATABASE %I OWNER TO %I', current_database(), owner_role);
    EXECUTE format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database());
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO %I', current_database(), app_role);

    -- Every schema, table, view and routine the app's schemas hold belongs to the owner. A
    -- sequence a column owns follows its table, and an extension's members stay the extension's.
    FOR object_name IN
        SELECT format('SCHEMA %I', n.nspname)
        FROM pg_namespace AS n
        WHERE n.nspname NOT IN ('pg_catalog', 'information_schema', 'public')
            AND n.nspname NOT LIKE 'pg\_%'
            AND n.nspowner <> owner_role::regrole
        UNION ALL
        SELECT format('%s %s', CASE c.relkind WHEN 'S' THEN 'SEQUENCE' WHEN 'v' THEN 'VIEW'
                                              WHEN 'm' THEN 'MATERIALIZED VIEW' ELSE 'TABLE' END, c.oid::regclass)
        FROM pg_class AS c
        JOIN pg_namespace AS n ON n.oid = c.relnamespace
        WHERE c.relkind IN ('r', 'p', 'v', 'm', 'S')
            AND n.nspname NOT IN ('pg_catalog', 'information_schema')
            AND n.nspname NOT LIKE 'pg\_%'
            AND c.relowner <> owner_role::regrole
            AND NOT EXISTS (
                SELECT FROM pg_depend AS d
                WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid AND d.deptype IN ('a', 'i', 'e')
            )
        UNION ALL
        SELECT format('ROUTINE %s', p.oid::regprocedure)
        FROM pg_proc AS p
        JOIN pg_namespace AS n ON n.oid = p.pronamespace
        WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
            AND n.nspname NOT LIKE 'pg\_%'
            AND p.proowner <> owner_role::regrole
            AND NOT EXISTS (
                SELECT FROM pg_depend AS d
                WHERE d.classid = 'pg_proc'::regclass AND d.objid = p.oid AND d.deptype = 'e'
            )
    LOOP
        EXECUTE format('ALTER %s OWNER TO %I', object_name, owner_role);
    END LOOP;

    FOR schema_name IN
        SELECT n.nspname FROM pg_namespace AS n
        WHERE n.nspname NOT IN ('pg_catalog', 'information_schema') AND n.nspname NOT LIKE 'pg\_%'
    LOOP
        EXECUTE format('GRANT USAGE ON SCHEMA %I TO %I', schema_name, app_role);
        EXECUTE format('REVOKE CREATE ON SCHEMA %I FROM PUBLIC, %I', schema_name, app_role);
        EXECUTE format('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA %I TO %I', schema_name, app_role);
    END LOOP;

    -- A table where the app role holds any of the four is left as a migration narrowed it. Only
    -- one where it holds none is granted all four.
    FOR object_name IN
        SELECT c.oid::regclass::text
        FROM pg_class AS c
        JOIN pg_namespace AS n ON n.oid = c.relnamespace
        WHERE c.relkind IN ('r', 'p', 'v')
            AND n.nspname NOT IN ('pg_catalog', 'information_schema')
            AND n.nspname NOT LIKE 'pg\_%'
            AND NOT has_table_privilege(app_role, c.oid, 'SELECT, INSERT, UPDATE, DELETE')
    LOOP
        EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE %s TO %I', object_name, app_role);
    END LOOP;

    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %I',
                   owner_role, app_role);
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I GRANT USAGE, SELECT ON SEQUENCES TO %I', owner_role, app_role);
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I GRANT USAGE ON SCHEMAS TO %I', owner_role, app_role);
END;
$$;
