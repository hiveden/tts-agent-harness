"""Shared fixtures for e2e integration tests.

These tests hit the REAL dev-stack services:
- Postgres: localhost:55432 (harness:harness)
- MinIO:    localhost:59000 (minioadmin:minioadmin, bucket tts-harness)

NO testcontainers — relies on the A1-built dev stack being up.

All test episodes use an "e2e-" prefix to avoid polluting real data.
Each test cleans up its own data before and after.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from server.core.models import Base, Chunk, Episode, Event, StageRun, Take
from server.core.storage import MinIOStorage

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PG_URL = "postgresql+asyncpg://harness:harness@localhost:55432/harness"
MINIO_ENDPOINT = "localhost:59000"
MINIO_ACCESS_KEY = "minioadmin"
MINIO_SECRET_KEY = "minioadmin"
MINIO_BUCKET = "tts-harness"

E2E_PREFIX = "e2e-"


def _e2e_id() -> str:
    """Generate a unique e2e episode id."""
    return f"{E2E_PREFIX}{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Marker registration
# ---------------------------------------------------------------------------

def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "e2e: end-to-end integration test")


# Auto-apply e2e marker to all tests in this package
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "e2e" in str(item.fspath):
            item.add_marker(pytest.mark.e2e)


# ---------------------------------------------------------------------------
# DB engine + session (real Postgres)
# ---------------------------------------------------------------------------

def _make_engine():
    """Create a fresh engine (no caching — each event loop gets its own)."""
    return create_async_engine(PG_URL, future=True, pool_pre_ping=True)


def _make_maker(engine=None):
    """Create a sessionmaker bound to the given (or new) engine."""
    if engine is None:
        engine = _make_engine()
    return async_sessionmaker(engine, expire_on_commit=False)


# Per-test engine + maker stored here so helpers can grab them.
_current_engine = None
_current_maker: async_sessionmaker[AsyncSession] | None = None


def _get_maker() -> async_sessionmaker[AsyncSession]:
    """Return the current test's sessionmaker (set by db_session fixture)."""
    if _current_maker is None:
        raise RuntimeError("No active db_session fixture")
    return _current_maker


@pytest_asyncio.fixture()
async def db_session() -> AsyncIterator[AsyncSession]:
    """Async session on the real dev Postgres. Engine created per-test."""
    global _current_engine, _current_maker
    engine = _make_engine()
    maker = _make_maker(engine)
    _current_engine = engine
    _current_maker = maker
    async with maker() as session:
        yield session
    _current_engine = None
    _current_maker = None
    await engine.dispose()


# ---------------------------------------------------------------------------
# Storage (real MinIO)
# ---------------------------------------------------------------------------

@pytest.fixture()
def storage() -> MinIOStorage:
    return MinIOStorage(
        endpoint=MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        bucket=MINIO_BUCKET,
    )


# ---------------------------------------------------------------------------
# Cleanup helper
# ---------------------------------------------------------------------------

async def _cleanup_e2e_episodes(session: AsyncSession) -> None:
    """Delete all episodes (and cascading data) whose id starts with e2e-."""
    # Delete events first (no FK constraint from events to episodes).
    await session.execute(
        delete(Event).where(Event.episode_id.like(f"{E2E_PREFIX}%"))
    )
    # CASCADE will handle chunks/takes/stage_runs.
    await session.execute(
        delete(Episode).where(Episode.id.like(f"{E2E_PREFIX}%"))
    )
    await session.commit()


async def _cleanup_minio_prefix(storage: MinIOStorage, prefix: str) -> None:
    """Remove all objects under a prefix in MinIO."""
    import asyncio

    def _rm():
        objs = storage._client.list_objects(storage._bucket, prefix=prefix, recursive=True)
        for obj in objs:
            storage._client.remove_object(storage._bucket, obj.object_name)

    await asyncio.to_thread(_rm)


@pytest_asyncio.fixture(autouse=True)
async def cleanup(db_session: AsyncSession, storage: MinIOStorage) -> AsyncIterator[None]:
    """Clean up e2e test data before and after each test."""
    await _cleanup_e2e_episodes(db_session)
    yield
    # Post-test cleanup
    maker = _get_maker()
    async with maker() as session:
        await _cleanup_e2e_episodes(session)
    # Also clean MinIO e2e prefixes
    await _cleanup_minio_prefix(storage, f"episodes/{E2E_PREFIX}")


# ---------------------------------------------------------------------------
# FastAPI test client (ASGI transport — no real server needed)
# ---------------------------------------------------------------------------

# Session-scoped override state for the FastAPI app.
_api_session_maker: async_sessionmaker[AsyncSession] | None = None


async def _override_get_session() -> AsyncIterator[AsyncSession]:
    """DI override — yield a session from the real PG engine."""
    maker = _get_maker()
    async with maker() as session:
        yield session


def _override_get_storage() -> MinIOStorage:
    """DI override — return a real MinIO storage client."""
    return MinIOStorage(
        endpoint=MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        bucket=MINIO_BUCKET,
    )


def _make_mock_prefect_client() -> AsyncMock:
    client = AsyncMock()
    flow_run = MagicMock()
    flow_run.id = uuid4()
    client.create_flow_run_from_deployment = AsyncMock(return_value=flow_run)
    return client


async def _override_get_prefect_client() -> AsyncIterator[Any]:
    yield _make_mock_prefect_client()


@pytest_asyncio.fixture()
async def api_client() -> AsyncIterator[AsyncClient]:
    """httpx.AsyncClient wired to the real FastAPI app with real PG + MinIO."""
    from server.api.main import app
    from server.api.deps import get_session, get_storage, get_prefect_client

    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_storage] = _override_get_storage
    app.dependency_overrides[get_prefect_client] = _override_get_prefect_client

    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers exposed to tests
# ---------------------------------------------------------------------------

def make_script_json(title: str = "E2E Test Episode", segments: list[dict] | None = None) -> bytes:
    """Build a minimal script.json for testing."""
    if segments is None:
        segments = [
            {"id": 1, "type": "hook", "text": "This is the first sentence for testing."},
            {"id": 2, "type": "content", "text": "This is the second sentence for testing."},
        ]
    return json.dumps({"title": title, "segments": segments}, ensure_ascii=False).encode()


def e2e_id() -> str:
    return _e2e_id()


# 1-second silent WAV (mono, 16kHz, 16-bit PCM)
def make_silent_wav(duration_s: float = 1.0, sample_rate: int = 16000) -> bytes:
    """Generate a valid WAV file of silence."""
    import struct
    import wave as wave_mod
    import io

    num_samples = int(sample_rate * duration_s)
    buf = io.BytesIO()
    with wave_mod.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * num_samples)
    return buf.getvalue()
