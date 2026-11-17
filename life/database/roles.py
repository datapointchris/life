"""The database's owner and app roles, converged from `roles.sql` as the server's superuser.

Production runs the same file through psql on the Postgres container's own socket, from
`scripts/converge-database-roles.sh`. This is the caller for a stack that reaches its server over
TCP, as the test suite's does.
"""

import os
from pathlib import Path

import structlog
from sqlalchemy import create_engine
from sqlalchemy import text

from life.config import postgres_url

logger = structlog.get_logger()

CONVERGE_ROLES = (Path(__file__).parent / 'roles.sql').read_text()
SUPERUSER = 'postgres'


def owner_role(database: str) -> str:
    """The role named for the database, which owns every object and runs the migrations."""
    return database


def app_role(database: str) -> str:
    """The role the API and the scheduler log in as, holding DML and no DDL."""
    return f'{database}_app'


def converge_database_roles(superuser_uri: str, owner_password: str, app_password: str) -> None:
    """Create or update both roles and their grants, in one transaction on the superuser's connection."""
    engine = create_engine(superuser_uri)
    try:
        with engine.begin() as connection:
            for setting, value in (('life_roles.owner_password', owner_password), ('life_roles.app_password', app_password)):
                connection.execute(text('SELECT set_config(:setting, :value, true)'), {'setting': setting, 'value': value})
            # A query with no parameters, so psycopg reads format()'s % as SQL rather than a placeholder.
            connection.connection.cursor().execute(CONVERGE_ROLES)
    finally:
        engine.dispose()


def main() -> None:
    """Converge the roles on the server POSTGRES_HOST names, as `postgres`, from the environment.

    POSTGRES_SUPERUSER_PASSWORD logs in. POSTGRES_OWNER_PASSWORD and POSTGRES_PASSWORD, the app's,
    become the two roles' passwords. The test stack's API container holds all three.
    """
    database = os.environ['POSTGRES_DB']
    superuser_uri = postgres_url(
        SUPERUSER, os.environ['POSTGRES_SUPERUSER_PASSWORD'], os.environ['POSTGRES_HOST'], int(os.environ['POSTGRES_PORT']), database
    )
    converge_database_roles(superuser_uri, os.environ['POSTGRES_OWNER_PASSWORD'], os.environ['POSTGRES_PASSWORD'])
    logger.info('database_roles_converged', database=database, owner=owner_role(database), app=app_role(database))


if __name__ == '__main__':
    main()
