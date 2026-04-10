"""E2E tests — chunk-level operations (edit, retry, P1 real chunking).

Tests run against real Postgres + MinIO. P2 is mocked.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from server.core.repositories import ChunkRepo, EpisodeRepo, TakeRepo
from server.core.storage import MinIOStorage, episode_script_key
from server.flows.tasks.p1_chunk import P1Context, _run_p1

from .conftest import _get_maker, e2e_id, make_script_json, make_silent_wav
from .test_full_pipeline import FakeFishClient, _fake_http_client_factory, _wire_task_dependencies


async def _setup_episode_with_chunks(ep_id: str, storage: MinIOStorage) -> list[str]:
    """Create episode, run P1, return chunk IDs."""
    from server.core.domain import EpisodeCreate

    maker = _get_maker()
    script = make_script_json("Chunk Ops Test", segments=[
        {"id": 1, "type": "hook", "text": "First sentence for chunk operations test."},
        {"id": 2, "type": "content", "text": "Second sentence for chunk operations test."},
    ])

    key = episode_script_key(ep_id)
    await storage.upload_bytes(key, script, "application/json")

    async with maker() as session:
        repo = EpisodeRepo(session)
        await repo.create(EpisodeCreate(
            id=ep_id,
            title="Chunk Ops",
            script_uri=f"s3://tts-harness/{key}",
        ))
        await session.commit()

    ctx = P1Context(session_maker=maker, storage=storage)
    p1_result = await _run_p1(ctx, ep_id)

    return [c.id for c in p1_result.chunks]


# ---------------------------------------------------------------------------
# 1. P1 real chunking — verify chunks in DB
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_p1_real_chunking(storage: MinIOStorage):
    """Run real P1 chunking and verify chunks exist in DB with correct fields."""
    ep_id = e2e_id()
    chunk_ids = await _setup_episode_with_chunks(ep_id, storage)

    assert len(chunk_ids) >= 2

    maker = _get_maker()
    async with maker() as session:
        chunks = await ChunkRepo(session).list_by_episode(ep_id)
        for chunk in chunks:
            assert chunk.text != ""
            assert chunk.text_normalized != ""
            assert chunk.char_count > 0
            assert chunk.status == "pending"
            assert chunk.episode_id == ep_id


# ---------------------------------------------------------------------------
# 2. Edit chunk text — verify DB update via API
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_edit_chunk_text(api_client: AsyncClient, storage: MinIOStorage):
    """Edit chunk text_normalized via API and verify DB update."""
    ep_id = e2e_id()
    chunk_ids = await _setup_episode_with_chunks(ep_id, storage)
    cid = chunk_ids[0]

    # Edit via API
    resp = await api_client.post(
        f"/episodes/{ep_id}/chunks/{cid}/edit",
        params={"text_normalized": "Modified text for testing."},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["updated"] == 1

    # Verify in DB
    maker = _get_maker()
    async with maker() as session:
        chunk = await ChunkRepo(session).get(cid)
        assert chunk is not None
        assert chunk.text_normalized == "Modified text for testing."
        assert chunk.last_edited_at is not None
        # char_count should be recomputed
        assert chunk.char_count == len("Modified text for testing.")


# ---------------------------------------------------------------------------
# 3. Retry chunk (mock P2) — verify new take generated
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_retry_chunk_generates_new_take(storage: MinIOStorage):
    """Run P2 twice on the same chunk and verify two takes exist."""
    ep_id = e2e_id()
    _wire_task_dependencies(storage)
    chunk_ids = await _setup_episode_with_chunks(ep_id, storage)
    cid = chunk_ids[0]

    from server.flows.tasks.p2_synth import run_p2_synth

    # First P2 run
    result1 = await run_p2_synth(cid)
    take_id_1 = result1.take_id

    # Second P2 run (simulates retry)
    result2 = await run_p2_synth(cid)
    take_id_2 = result2.take_id

    assert take_id_1 != take_id_2

    # Verify two takes exist in DB
    maker = _get_maker()
    async with maker() as session:
        takes = await TakeRepo(session).list_by_chunk(cid)
        assert len(takes) == 2
        take_ids = {t.id for t in takes}
        assert take_id_1 in take_ids
        assert take_id_2 in take_ids

        # selected_take_id should be the latest
        chunk = await ChunkRepo(session).get(cid)
        assert chunk is not None
        assert chunk.selected_take_id == take_id_2


# ---------------------------------------------------------------------------
# 4. Edit non-existent chunk → 404
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_edit_nonexistent_chunk(api_client: AsyncClient):
    """Editing a non-existent chunk should return 404."""
    ep_id = e2e_id()
    resp = await api_client.post(
        f"/episodes/{ep_id}/chunks/fake-chunk-id/edit",
        params={"text_normalized": "nope"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 5. Retry via API — verify flow_run_id returned
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_retry_via_api(api_client: AsyncClient, storage: MinIOStorage):
    """POST /episodes/{id}/chunks/{cid}/retry returns a flow_run_id."""
    ep_id = e2e_id()
    chunk_ids = await _setup_episode_with_chunks(ep_id, storage)
    cid = chunk_ids[0]

    resp = await api_client.post(
        f"/episodes/{ep_id}/chunks/{cid}/retry",
        params={"from_stage": "p2"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "flow_run_id" in body
    assert body["flow_run_id"] != ""
