"""The Postgres and Redis a pytest session runs against.

Each is the server TEST_DATABASE_URL or TEST_REDIS_URL names, where the
environment provides one. Otherwise the session starts its own on a port Docker
picks, so two checkouts run pytest at once and neither can truncate the other's
tables. testcontainers' reaper removes those when the session ends, however it
ends.
"""

import copy
import logging
import os
from pathlib import Path
from urllib.parse import unquote
from urllib.parse import urlsplit

import pytest
import yaml
from testcontainers.community.postgres import PostgresContainer
from testcontainers.community.redis import RedisContainer
from testcontainers.core.config import testcontainers_config
from testcontainers.core.container import DockerContainer

from life.config import Settings
from life.config import postgres_url
from life.database.initialization import full_initialization
from life.database.roles import app_role
from life.database.roles import converge_database_roles
from life.database.roles import owner_role

logger = logging.getLogger(__name__)

# Readiness is checked every 100ms instead of every second, under the same two-minute ceiling.
testcontainers_config.sleep_time = 0.1
testcontainers_config.max_tries = 1200

REPO_ROOT = Path(__file__).resolve().parents[1]
POSTGRES_USER = 'postgres'
POSTGRES_PASSWORD = 'postgres'
POSTGRES_DB = 'life'
POSTGRES_DATA = '/var/lib/postgresql/data'
OWNER_PASSWORD = os.environ['POSTGRES_OWNER_PASSWORD']
APP_PASSWORD = os.environ['POSTGRES_PASSWORD']


def as_owner(settings: Settings) -> Settings:
    """A copy of `settings` logged in as the database's owner, for the migrations and for emptying tables."""
    owner = copy.copy(settings)
    owner.postgres = copy.copy(settings.postgres)
    owner.sqlalchemy = copy.copy(settings.sqlalchemy)
    for database in (owner.postgres, owner.sqlalchemy):
        database.username = owner_role(database.database)
        database.password = OWNER_PASSWORD
    return owner


def production_image(service: str) -> str:
    """The image production runs a service on, so the tests meet the same major version."""
    compose = yaml.safe_load((REPO_ROOT / 'docker-compose.yml').read_text())
    return compose['services'][service]['image']


class PrivateServices:
    """Points `settings` at this session's Postgres and Redis.

    A container is started for whichever one TEST_DATABASE_URL or TEST_REDIS_URL does not name. The
    database URL logs in as the server's superuser, which only creates the owner and app roles.
    The migrations run as the owner, and `settings` logs in as the app role, as production does.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.started: list[DockerContainer] = []

    def __enter__(self):
        try:
            self.start()
        except Exception as e:
            self.stop()
            pytest.exit(f'Could not start the Postgres and Redis this session runs against: {e}', returncode=1)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        return False

    def start(self) -> None:
        redis = urlsplit(os.environ.get('TEST_REDIS_URL') or self.start_redis())
        postgres = urlsplit(os.environ.get('TEST_DATABASE_URL') or self.start_postgres())
        assert postgres.hostname is not None and postgres.port is not None, 'the database URL names a host and a port'
        assert redis.hostname is not None and redis.port is not None, 'the Redis URL names a host and a port'
        database_name = postgres.path.lstrip('/')
        superuser = unquote(postgres.username or '')
        superuser_password = unquote(postgres.password or '')
        converge_database_roles(
            postgres_url(superuser, superuser_password, postgres.hostname, postgres.port, database_name), OWNER_PASSWORD, APP_PASSWORD
        )
        for database in (self.settings.postgres, self.settings.sqlalchemy):
            database.host = postgres.hostname
            database.port = postgres.port
            database.username = app_role(database_name)
            database.password = APP_PASSWORD
            database.database = database_name
        self.settings.redis.host = redis.hostname
        self.settings.redis.port = redis.port
        self.settings.redis.password = unquote(redis.password or '')
        if redis.path.strip('/'):
            self.settings.redis.db = int(redis.path.strip('/'))
        logger.info(f'session services: postgres {postgres.hostname}:{postgres.port}, redis {redis.hostname}:{redis.port}')
        full_initialization(as_owner(self.settings))

    def start_postgres(self) -> str:
        """Start this session's own Postgres and return its URL."""
        # Durability is off and the data lives in memory: nothing outlives the session.
        container = (
            PostgresContainer(
                production_image('postgres'), username=POSTGRES_USER, password=POSTGRES_PASSWORD, dbname=POSTGRES_DB, driver=None
            )
            .with_tmpfs_mount(POSTGRES_DATA)
            .with_command(['postgres', '-c', 'fsync=off', '-c', 'synchronous_commit=off', '-c', 'full_page_writes=off'])
        )
        container.start()
        self.started.append(container)
        host, port = container.get_container_host_ip(), container.get_exposed_port(5432)
        return f'postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{host}:{port}/{POSTGRES_DB}'

    def start_redis(self) -> str:
        """Start this session's own Redis and return its URL."""
        container = RedisContainer(production_image('redis')).with_command(['redis-server', '--save', '', '--appendonly', 'no'])
        container.start()
        self.started.append(container)
        return f'redis://{container.get_container_host_ip()}:{container.get_exposed_port(6379)}'

    def stop(self) -> None:
        while self.started:
            self.started.pop().stop()
