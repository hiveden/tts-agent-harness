"""Integration tests for FastAPI routes.

Uses httpx AsyncClient with in-memory SQLite. Prefect client is always mocked.
"""

from __future__ import annotations

import io
import json
import os
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from server.core.domain import ChunkInput
from server.core.models import Base
from server.core.repositories import ChunkRepo, EpisodeRepo, TakeRepo
from server.core.domain import EpisodeCreate, TakeAppend


# ---------------------------------------------------------------------------
# Test-scoped app + client
# ---------------------------------------------------------------------------

_engine = None
_maker = None


async def _override_get_session() -> AsyncIterator[AsyncSession]:
    global _maker
    async with _maker() as session:
        yield session


def _override_get_storage() -> Any:
    """Return a mock storage that captures uploads."""
    storage = MagicMock()
    storage.upload_bytes = AsyncMock(return_value="s3://tts-harness/test/script.json")
    storage.ensure_bucket = AsyncMock()
    return storage


def _make_mock_prefect_client():
    """Build a mock prefect client."""
    client = AsyncMock()
    flow_run = MagicMock()
    flow_run.id = uuid4()
    client.create_flow_run_from_deployment = AsyncMock(return_value=flow_run)
    return client


async def _override_get_prefect_client() -> AsyncIterator[Any]:
    yield _make_mock_prefect_client()


@pytest_asyncio.fixture()
async def client() -> AsyncIterator[AsyncClient]:
    global _engine, _maker

    _engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    _maker = async_sessionmaker(_engine, expire_on_commit=False)

    # Import app after engine setup
    from server.api.main import app
    from server.api.deps import get_session, get_storage, get_prefect_client

    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_storage] = _override_get_storage
    app.dependency_overrides[get_prefect_client] = _override_get_prefect_client

    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    await _engine.dispose()


@pytest_asyncio.fixture()
async def seeded_client(client: AsyncClient) -> AsyncClient:
    """Client with a pre-created episode + chunks."""
    # Create episode
    script = json.dumps({"title": "Test", "segments": [{"id": 1, "text": "hello"}]})
    resp = await client.post(
        "/episodes",
        data={"id": "ep-test", "title": "Test Episode"},
        files={"script": ("script.json", io.BytesIO(script.encode()), "application/json")},
    )
    assert resp.status_code == 201

    # Seed chunks via direct DB
    global _maker
    async with _maker() as session:
        chunk_repo = ChunkRepo(session)
        await chunk_repo.bulk_insert([
            ChunkInput(
                id="ep-test:shot01:0",
                episode_id="ep-test",
                shot_id="shot01",
                idx=0,
                text="hello world",
                text_normalized="hello world",
                char_count=11,
            ),
            ChunkInput(
                id="ep-test:shot01:1",
                episode_id="ep-test",
                shot_id="shot01",
                idx=1,
                text="second chunk",
                text_normalized="second chunk",
                char_count=12,
            ),
        ])
        # Seed a take
        take_repo = TakeRepo(session)
        await take_repo.append(TakeAppend(
            id="take-001",
            chunk_id="ep-test:shot01:0",
            audio_uri="s3://tts-harness/test.wav",
            duration_s=1.5,
            params={"temperature": 0.7},
        ))
        await session.commit()

    return client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHealthz:
    async def test_healthz(self, client: AsyncClient):
        resp = await client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestEpisodeCRUD:
    async def test_create_episode(self, client: AsyncClient):
        script = json.dumps({"title": "My Ep", "segments": []})
        resp = await client.post(
            "/episodes",
            data={"id": "ep-1", "title": "My Episode"},
            files={"script": ("s.json", io.BytesIO(script.encode()), "application/json")},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["id"] == "ep-1"
        assert data["title"] == "My Episode"
        assert data["status"] == "empty"

    async def test_create_duplicate_episode(self, client: AsyncClient):
        script = json.dumps({"title": "Dup", "segments": []})
        files = {"script": ("s.json", io.BytesIO(script.encode()), "application/json")}
        resp1 = await client.post("/episodes", data={"id": "dup"}, files=files)
        assert resp1.status_code == 201

        files2 = {"script": ("s.json", io.BytesIO(script.encode()), "application/json")}
        resp2 = await client.post("/episodes", data={"id": "dup"}, files=files2)
        assert resp2.status_code == 422
        assert resp2.json()["error"] == "invalid_input"

    async def test_create_invalid_json(self, client: AsyncClient):
        resp = await client.post(
            "/episodes",
            data={"id": "bad"},
            files={"script": ("s.json", io.BytesIO(b"not json"), "application/json")},
        )
        assert resp.status_code == 422
        assert resp.json()["error"] == "invalid_input"

    async def test_list_episodes(self, client: AsyncClient):
        script = json.dumps({"title": "X", "segments": []})
        for i in range(3):
            files = {"script": ("s.json", io.BytesIO(script.encode()), "application/json")}
            await client.post("/episodes", data={"id": f"ep-{i}"}, files=files)

        resp = await client.get("/episodes")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 3

    async def test_get_episode(self, seeded_client: AsyncClient):
        resp = await seeded_client.get("/episodes/ep-test")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "ep-test"
        assert len(data["chunks"]) == 2

    async def test_get_episode_not_found(self, client: AsyncClient):
        resp = await client.get("/episodes/nope")
        assert resp.status_code == 404

    async def test_episode_detail_nested_structure(self, seeded_client: AsyncClient):
        resp = await seeded_client.get("/episodes/ep-test")
        data = resp.json()
        chunk0 = data["chunks"][0]
        assert "takes" in chunk0
        assert "stage_runs" in chunk0
        assert len(chunk0["takes"]) == 1
        assert chunk0["takes"][0]["id"] == "take-001"

    async def test_delete_episode(self, seeded_client: AsyncClient):
        resp = await seeded_client.delete("/episodes/ep-test")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True

        resp2 = await seeded_client.get("/episodes/ep-test")
        assert resp2.status_code == 404

    async def test_delete_nonexistent(self, client: AsyncClient):
        resp = await client.delete("/episodes/nope")
        assert resp.status_code == 404


class TestRunEpisode:
    async def test_trigger_run(self, seeded_client: AsyncClient):
        resp = await seeded_client.post("/episodes/ep-test/run")
        assert resp.status_code == 200
        data = resp.json()
        assert "flow_run_id" in data

    async def test_trigger_run_not_found(self, client: AsyncClient):
        resp = await client.post("/episodes/nope/run")
        assert resp.status_code == 404


class TestChunkEdit:
    async def test_edit_chunk(self, seeded_client: AsyncClient):
        resp = await seeded_client.post(
            "/episodes/ep-test/chunks/ep-test:shot01:0/edit",
            params={"text_normalized": "modified text"},
        )
        assert resp.status_code == 200
        assert resp.json()["updated"] == 1

        # Verify via GET
        resp2 = await seeded_client.get("/episodes/ep-test")
        chunk = resp2.json()["chunks"][0]
        assert chunk["text_normalized"] == "modified text"

    async def test_edit_chunk_not_found(self, client: AsyncClient):
        resp = await client.post(
            "/episodes/ep-test/chunks/nonexistent/edit",
            params={"text_normalized": "x"},
        )
        assert resp.status_code == 404


class TestChunkRetry:
    async def test_retry_chunk(self, seeded_client: AsyncClient):
        resp = await seeded_client.post(
            "/episodes/ep-test/chunks/ep-test:shot01:0/retry",
            params={"from_stage": "p2"},
        )
        assert resp.status_code == 200
        assert "flow_run_id" in resp.json()

    async def test_retry_chunk_not_found(self, client: AsyncClient):
        resp = await client.post(
            "/episodes/nope/chunks/bad/retry",
        )
        assert resp.status_code == 404


class TestFinalizeTake:
    async def test_finalize_take(self, seeded_client: AsyncClient):
        resp = await seeded_client.post(
            "/episodes/ep-test/chunks/ep-test:shot01:0/finalize-take",
            params={"take_id": "take-001"},
        )
        assert resp.status_code == 200
        assert "flow_run_id" in resp.json()

    async def test_finalize_take_not_found(self, seeded_client: AsyncClient):
        resp = await seeded_client.post(
            "/episodes/ep-test/chunks/ep-test:shot01:0/finalize-take",
            params={"take_id": "nonexistent-take"},
        )
        assert resp.status_code == 404


class TestAuth:
    async def test_dev_mode_no_token_passes(self, client: AsyncClient):
        """When HARNESS_API_TOKEN is not set, all requests pass."""
        resp = await client.get("/healthz")
        assert resp.status_code == 200

    async def test_valid_token_passes(self):
        """When HARNESS_API_TOKEN is set and correct token is provided."""
        global _engine, _maker

        _engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
        async with _engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        _maker = async_sessionmaker(_engine, expire_on_commit=False)

        from server.api.main import app
        from server.api.deps import get_session, get_storage, get_prefect_client

        app.dependency_overrides[get_session] = _override_get_session
        app.dependency_overrides[get_storage] = _override_get_storage
        app.dependency_overrides[get_prefect_client] = _override_get_prefect_client

        transport = ASGITransport(app=app)  # type: ignore[arg-type]

        with patch.dict(os.environ, {"HARNESS_API_TOKEN": "test-secret"}):
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get(
                    "/healthz",
                    headers={"Authorization": "Bearer test-secret"},
                )
                assert resp.status_code == 200

        app.dependency_overrides.clear()
        await _engine.dispose()

    async def test_wrong_token_rejected(self):
        """When HARNESS_API_TOKEN is set but wrong token provided → 401."""
        global _engine, _maker

        _engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
        async with _engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        _maker = async_sessionmaker(_engine, expire_on_commit=False)

        from server.api.main import app
        from server.api.deps import get_session, get_storage, get_prefect_client

        app.dependency_overrides[get_session] = _override_get_session
        app.dependency_overrides[get_storage] = _override_get_storage
        app.dependency_overrides[get_prefect_client] = _override_get_prefect_client

        transport = ASGITransport(app=app)  # type: ignore[arg-type]

        with patch.dict(os.environ, {"HARNESS_API_TOKEN": "real-secret"}):
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get(
                    "/healthz",
                    headers={"Authorization": "Bearer wrong-token"},
                )
                assert resp.status_code == 401
                assert resp.json()["error"] == "unauthorized"

        app.dependency_overrides.clear()
        await _engine.dispose()

    async def test_missing_token_rejected(self):
        """When HARNESS_API_TOKEN is set but no header → 401."""
        global _engine, _maker

        _engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
        async with _engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        _maker = async_sessionmaker(_engine, expire_on_commit=False)

        from server.api.main import app
        from server.api.deps import get_session, get_storage, get_prefect_client

        app.dependency_overrides[get_session] = _override_get_session
        app.dependency_overrides[get_storage] = _override_get_storage
        app.dependency_overrides[get_prefect_client] = _override_get_prefect_client

        transport = ASGITransport(app=app)  # type: ignore[arg-type]

        with patch.dict(os.environ, {"HARNESS_API_TOKEN": "real-secret"}):
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get("/healthz")
                assert resp.status_code == 401

        app.dependency_overrides.clear()
        await _engine.dispose()
