"""Dependency injection helpers for FastAPI route handlers.

All heavy resources (DB session, storage, prefect client) are resolved here so
that route handlers stay thin.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from server.core.db import get_session as _core_get_session
from server.core.storage import MinIOStorage


# ---------------------------------------------------------------------------
# DB session
# ---------------------------------------------------------------------------


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield an ``AsyncSession`` scoped to one request."""
    async for s in _core_get_session():
        yield s


# ---------------------------------------------------------------------------
# MinIO storage
# ---------------------------------------------------------------------------

_storage_singleton: MinIOStorage | None = None


def _build_storage() -> MinIOStorage:
    return MinIOStorage(
        endpoint=os.environ.get("MINIO_ENDPOINT", "localhost:59000"),
        access_key=os.environ.get("MINIO_ACCESS_KEY", "minioadmin"),
        secret_key=os.environ.get("MINIO_SECRET_KEY", "minioadmin"),
        bucket=os.environ.get("MINIO_BUCKET", "tts-harness"),
    )


def get_storage() -> MinIOStorage:
    global _storage_singleton
    if _storage_singleton is None:
        _storage_singleton = _build_storage()
    return _storage_singleton


# ---------------------------------------------------------------------------
# Prefect client
# ---------------------------------------------------------------------------


async def get_prefect_client() -> AsyncIterator[Any]:
    """Yield a Prefect async client.

    Usage in routes::

        @router.post("/episodes/{id}/run")
        async def run_episode(id: str, client=Depends(get_prefect_client)):
            await client.create_flow_run_from_deployment(...)
    """
    from prefect.client.orchestration import get_client

    async with get_client() as client:
        yield client
