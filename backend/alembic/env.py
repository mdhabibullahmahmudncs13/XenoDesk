"""Alembic environment. Reads the URL from app settings so migrations and the app agree."""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

# Importing the models package registers every table on Base.metadata.
import xenovarients.models  # noqa: F401
from alembic import context
from xenovarients.core.config import get_settings
from xenovarients.db.base import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _migration_url() -> str:
    """Migrations need DDL rights, so they run as the schema owner.

    The application connects as a restricted role that is subject to Row Level
    Security; that role cannot create, alter or drop tables. ``migration_database_url``
    points at the owner connection.
    """
    settings = get_settings()
    url = settings.migration_database_url or settings.database_url
    return str(url).replace("+asyncpg", "")


config.set_main_option("sqlalchemy.url", _migration_url())

target_metadata = Base.metadata


def _assert_identifier_lengths() -> None:
    """Postgres truncates identifiers at 63 chars, which silently breaks constraint lookups."""
    too_long = [
        c.name
        for t in target_metadata.tables.values()
        for c in (*t.constraints, *t.indexes)
        if c.name and len(c.name) > 63
    ]
    if too_long:
        raise RuntimeError(f"identifier(s) exceed Postgres' 63-char limit: {too_long}")


_assert_identifier_lengths()


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
