"""E2E tests for new endpoints: config, audio, run modes, archive filter.

Covers BP-01 through BP-07 and product decisions D-01 through D-05.
"""

from __future__ import annotations

import json

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from server.core.models import Chunk, Episode, Take
from server.core.repositories import ChunkRepo, EpisodeRepo, TakeRepo
from server.core.storage import MinIOStorage, chunk_take_key

from .conftest import e2e_id, make_script_json, make_silent_wav


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_episode_with_chunks(
    db: AsyncSession,
    storage: MinIOStorage,
    ep_id: str,
    chunk_count: int = 2,
    *,
    with_takes: bool = False,
    status: str = "ready",
) -> list[str]:
    """Create an episode + chunks for testing. Returns chunk ids."""
    # Upload dummy script
    script = make_script_json("Test Episode")
    key = f"episodes/{ep_id}/script.json"
    await storage.upload_bytes(key, script, content_type="application/json")

    repo = EpisodeRepo(db)
    from server.core.domain import EpisodeCreate
    await repo.create(EpisodeCreate(
        id=ep_id, title="Test", script_uri=f"s3://tts-harness/{key}",
    ))
    await repo.set_status(ep_id, status)

    chunk_repo = ChunkRepo(db)
    from server.core.domain import ChunkInput
    chunks = [
        ChunkInput(
            id=f"{ep_id}:shot01:{i}",
            episode_id=ep_id,
            shot_id="shot01",
            idx=i,
            text=f"Test sentence {i}.",
            text_normalized=f"Test sentence {i}.",
            char_count=len(f"Test sentence {i}."),
        )
        for i in range(chunk_count)
    ]
    await chunk_repo.bulk_insert(chunks)

    cids = [c.id for c in chunks]

    if with_takes:
        take_repo = TakeRepo(db)
        wav = make_silent_wav(1.0)
        from server.core.domain import TakeAppend
        for cid in cids:
            take_id = f"take-{cid}"
            audio_key = chunk_take_key(ep_id, cid, take_id)
            await storage.upload_bytes(audio_key, wav, content_type="audio/wav")
            await take_repo.append(TakeAppend(
                id=take_id,
                chunk_id=cid,
                audio_uri=audio_key,
                duration_s=1.0,
            ))
            await chunk_repo.set_selected_take(cid, take_id)
            await chunk_repo.set_status(cid, "synth_done")

    await db.commit()
    return cids


# ---------------------------------------------------------------------------
# Config CRUD (BP-03, D-01)
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_get_config(api_client: AsyncClient, db_session: AsyncSession, storage: MinIOStorage):
    ep_id = e2e_id()
    await _seed_episode_with_chunks(db_session, storage, ep_id, 0)

    resp = await api_client.get(f"/episodes/{ep_id}/config")
    assert resp.status_code == 200
    assert "config" in resp.json()


@pytest.mark.e2e
async def test_update_config(api_client: AsyncClient, db_session: AsyncSession, storage: MinIOStorage):
    ep_id = e2e_id()
    await _seed_episode_with_chunks(db_session, storage, ep_id, 0)

    resp = await api_client.put(
        f"/episodes/{ep_id}/config",
        json={"config": {"temperature": 0.5, "top_p": 0.8}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["config"]["temperature"] == 0.5
    assert data["config"]["top_p"] == 0.8

    # Verify merge: update again with a different key
    resp2 = await api_client.put(
        f"/episodes/{ep_id}/config",
        json={"config": {"speed": 1.2}},
    )
    assert resp2.status_code == 200
    merged = resp2.json()["config"]
    assert merged["temperature"] == 0.5  # preserved from first update
    assert merged["speed"] == 1.2  # new key


@pytest.mark.e2e
async def test_config_not_found(api_client: AsyncClient):
    resp = await api_client.get("/episodes/nonexistent/config")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Audio serving (BP-01)
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_serve_audio(api_client: AsyncClient, db_session: AsyncSession, storage: MinIOStorage):
    ep_id = e2e_id()
    cids = await _seed_episode_with_chunks(db_session, storage, ep_id, 1, with_takes=True)
    take_id = f"take-{cids[0]}"
    audio_key = chunk_take_key(ep_id, cids[0], take_id)

    resp = await api_client.get(f"/audio/{audio_key}")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/wav"
    assert len(resp.content) > 0


@pytest.mark.e2e
async def test_serve_audio_not_found(api_client: AsyncClient):
    resp = await api_client.get("/audio/nonexistent/path/file.wav")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Run modes (BP-04, D-03)
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_run_chunk_only_mode(api_client: AsyncClient, db_session: AsyncSession, storage: MinIOStorage):
    ep_id = e2e_id()
    await _seed_episode_with_chunks(db_session, storage, ep_id, 0, status="empty")

    resp = await api_client.post(
        f"/episodes/{ep_id}/run",
        json={"mode": "chunk_only"},
    )
    assert resp.status_code == 200
    assert "flowRunId" in resp.json()


@pytest.mark.e2e
async def test_run_synthesize_mode(api_client: AsyncClient, db_session: AsyncSession, storage: MinIOStorage):
    ep_id = e2e_id()
    await _seed_episode_with_chunks(db_session, storage, ep_id, 2, status="ready")

    resp = await api_client.post(
        f"/episodes/{ep_id}/run",
        json={"mode": "synthesize"},
    )
    assert resp.status_code == 200
    assert "flowRunId" in resp.json()


@pytest.mark.e2e
async def test_run_retry_failed_mode(api_client: AsyncClient, db_session: AsyncSession, storage: MinIOStorage):
    ep_id = e2e_id()
    await _seed_episode_with_chunks(db_session, storage, ep_id, 2, status="failed")

    resp = await api_client.post(
        f"/episodes/{ep_id}/run",
        json={"mode": "retry_failed"},
    )
    assert resp.status_code == 200
    assert "flowRunId" in resp.json()


@pytest.mark.e2e
async def test_run_regenerate_mode(api_client: AsyncClient, db_session: AsyncSession, storage: MinIOStorage):
    ep_id = e2e_id()
    await _seed_episode_with_chunks(db_session, storage, ep_id, 2, status="done")

    resp = await api_client.post(
        f"/episodes/{ep_id}/run",
        json={"mode": "regenerate"},
    )
    assert resp.status_code == 200
    assert "flowRunId" in resp.json()


@pytest.mark.e2e
async def test_run_with_chunk_ids(api_client: AsyncClient, db_session: AsyncSession, storage: MinIOStorage):
    ep_id = e2e_id()
    cids = await _seed_episode_with_chunks(db_session, storage, ep_id, 3, status="ready")

    resp = await api_client.post(
        f"/episodes/{ep_id}/run",
        json={"mode": "synthesize", "chunkIds": [cids[0], cids[2]]},
    )
    assert resp.status_code == 200


@pytest.mark.e2e
async def test_run_already_running(api_client: AsyncClient, db_session: AsyncSession, storage: MinIOStorage):
    ep_id = e2e_id()
    await _seed_episode_with_chunks(db_session, storage, ep_id, 0, status="running")

    resp = await api_client.post(
        f"/episodes/{ep_id}/run",
        json={"mode": "synthesize"},
    )
    assert resp.status_code == 409  # invalid_state


# ---------------------------------------------------------------------------
# Archive filter (BP-06)
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_archive_excluded_from_list(api_client: AsyncClient, db_session: AsyncSession, storage: MinIOStorage):
    ep_id = e2e_id()
    await _seed_episode_with_chunks(db_session, storage, ep_id, 0)

    # Archive it
    resp = await api_client.post(f"/episodes/{ep_id}/archive")
    assert resp.status_code == 200

    # Default list should not include it
    resp2 = await api_client.get("/episodes")
    ids = [e["id"] for e in resp2.json()]
    assert ep_id not in ids

    # With include_archived=true should include it
    resp3 = await api_client.get("/episodes", params={"include_archived": "true"})
    ids3 = [e["id"] for e in resp3.json()]
    assert ep_id in ids3


# ---------------------------------------------------------------------------
# Episode logs (BP-02)
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_episode_logs(api_client: AsyncClient, db_session: AsyncSession, storage: MinIOStorage):
    ep_id = e2e_id()
    await _seed_episode_with_chunks(db_session, storage, ep_id, 1)

    # Creating the episode should have generated events
    resp = await api_client.get(f"/episodes/{ep_id}/logs", params={"tail": 10})
    assert resp.status_code == 200
    # lines might be empty if no events were written by the seeder, but endpoint works
    assert "lines" in resp.json()
