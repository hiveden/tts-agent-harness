"""
Alembic environment — async mode.

A1-Infra scope: this file only wires up the engine + migration context.
It does NOT import ORM models (A2-Domain will add `target_metadata` when
SQLAlchemy models land in server/core/models.py).

DATABASE_URL is read from the process environment; fallback is the dev
compose default. We translate asyncpg URLs to the sync psycopg2 URL when
alembic runs in "offline" mode.
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _resolve_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        # Dev default mirrors docker/.env.example
        url = "postgresql+asyncpg://harness:harness@localhost:5432/harness"
    return url


# No ORM metadata yet — A2-Domain will swap this to
# `from core.models import Base; target_metadata = Base.metadata`
target_metadata = None


def run_migrations_offline() -> None:
    """Offline mode: emit SQL to stdout, no DB connection."""
    url = _resolve_url()
    # Offline mode uses a sync driver URL for readability in generated SQL
    sync_url = url.replace("+asyncpg", "")
    context.configure(
        url=sync_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run migrations inside a sync wrapper."""
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = _resolve_url()

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
