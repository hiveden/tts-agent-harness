"""
server.core.db — async SQLAlchemy engine + session factory.

Scope for A1-Infra:
  - Expose `engine`, `AsyncSessionLocal`, and `get_session` (FastAPI DI).
  - Do NOT implement repositories, ORM models, or business logic — that
    is A2-Domain's job.

A2-Domain will import `AsyncSessionLocal` / `get_session` as-is.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


DEFAULT_DATABASE_URL = "postgresql+asyncpg://harness:harness@localhost:5432/harness"


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    """
    Return a process-wide singleton async engine.

    We use `lru_cache` so that tests can monkeypatch `os.environ` and call
    `get_engine.cache_clear()` to pick up a new DATABASE_URL.
    """
    return create_async_engine(
        _database_url(),
        echo=False,
        pool_pre_ping=True,
        future=True,
    )


@lru_cache(maxsize=1)
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=get_engine(),
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


# Convenient alias used by A2-Domain tests and future FastAPI deps.
AsyncSessionLocal = get_sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    """
    FastAPI dependency-injection helper.

    Usage (A9-API wave):

        from fastapi import Depends
        from server.core.db import get_session

        @router.get("/episodes")
        async def list_episodes(session: AsyncSession = Depends(get_session)):
            ...
    """
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        yield session
