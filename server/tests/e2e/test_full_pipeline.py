"""E2E tests — full pipeline (P1 → P2 → P3 → P5 → P6).

P2 (Fish TTS) and P3 (WhisperX) are mocked — we do NOT call real external
services. P1, P5, P6 use their real logic (P1 = text splitting, P5 = subtitle
algorithm, P6 = real ffmpeg).

Mock strategy:
- FakeFishClient: returns 1-second silent WAV bytes
- FakeWhisperXClient: returns a fake transcript JSON via httpx MockTransport
- Storage: real MinIO (writes fake but valid WAV/JSON data)
- DB: real Postgres

The test injects mocks via the task modules' configure_*_dependencies() DI.
"""

from __future__ import annotations

import io
import json
import struct
import wave as wave_mod
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from server.core.domain import FishTTSParams, P2Result, P3Result, P5Result, P6Result
from server.core.models import Episode
from server.core.repositories import ChunkRepo, EpisodeRepo, EventRepo
from server.core.storage import (
    MinIOStorage,
    chunk_subtitle_key,
    chunk_take_key,
    chunk_transcript_key,
    episode_script_key,
    final_srt_key,
    final_wav_key,
)
from server.flows.tasks.p1_chunk import P1Context, _run_p1

from .conftest import _get_maker, e2e_id, make_script_json, make_silent_wav


# ---------------------------------------------------------------------------
# Fake Fish TTS client
# ---------------------------------------------------------------------------


class FakeFishClient:
    """Returns a 1-second silent WAV. Implements the FishTTSClient interface."""

    async def synthesize(self, text: str, params: Any = None) -> bytes:
        return make_silent_wav(1.0)

    async def aclose(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Fake WhisperX HTTP transport
# ---------------------------------------------------------------------------


def _fake_whisperx_handler(request: httpx.Request) -> httpx.Response:
    """Mock httpx transport handler that returns a fake transcript."""
    if "/transcribe" in str(request.url):
        transcript = {
            "transcript": [
                {"word": "test", "start": 0.0, "end": 0.5, "score": 0.99},
                {"word": "sentence", "start": 0.5, "end": 1.0, "score": 0.98},
            ],
            "language": "en",
            "duration_s": 1.0,
        }
        return httpx.Response(200, json=transcript)
    return httpx.Response(404)


def _fake_http_client_factory() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(_fake_whisperx_handler))


# ---------------------------------------------------------------------------
# DI wiring helper
# ---------------------------------------------------------------------------


def _wire_task_dependencies(storage: MinIOStorage) -> None:
    """Inject fake clients into all task modules for e2e testing."""
    maker = _get_maker()

    # P2
    from server.flows.tasks.p2_synth import configure_p2_dependencies
    configure_p2_dependencies(
        session_factory=maker,
        storage=storage,
        fish_client_factory=lambda: FakeFishClient(),
    )

    # P3
    from server.flows.tasks.p3_transcribe import configure_p3_dependencies
    configure_p3_dependencies(
        session_factory=maker,
        storage=storage,
        http_client_factory=_fake_http_client_factory,
        whisperx_url="http://fake-whisperx:7860",
    )

    # P5
    from server.flows.tasks.p5_subtitles import configure_p5_dependencies
    configure_p5_dependencies(
        session_factory=maker,
        storage=storage,
    )


async def _create_episode_in_db(ep_id: str, title: str, script_bytes: bytes, storage: MinIOStorage) -> None:
    """Create an episode directly in DB + upload script to MinIO."""
    from server.core.domain import EpisodeCreate

    maker = _get_maker()
    key = episode_script_key(ep_id)
    await storage.upload_bytes(key, script_bytes, "application/json")

    async with maker() as session:
        repo = EpisodeRepo(session)
        await repo.create(EpisodeCreate(
            id=ep_id,
            title=title,
            script_uri=f"s3://tts-harness/{key}",
        ))
        await session.commit()


# ---------------------------------------------------------------------------
# Test: happy path — full P1 → P2 → P3 → P5 → P6
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_full_pipeline_happy_path(storage: MinIOStorage, db_session: AsyncSession):
    """End-to-end: create episode → run P1 → P2 → P3 → P5 → P6 → verify products."""
    ep_id = e2e_id()
    script_bytes = make_script_json("Full Pipeline Test", segments=[
        {"id": 1, "type": "hook", "text": "Hello world, this is a test."},
        {"id": 2, "type": "content", "text": "Second segment for the pipeline."},
    ])

    # Setup
    _wire_task_dependencies(storage)
    await _create_episode_in_db(ep_id, "Full Pipeline Test", script_bytes, storage)

    maker = _get_maker()

    # --- P1: chunk ---
    ctx = P1Context(session_maker=maker, storage=storage)
    p1_result = await _run_p1(ctx, ep_id)
    assert len(p1_result.chunks) >= 2

    # Verify episode status → ready
    async with maker() as session:
        ep = await EpisodeRepo(session).get(ep_id)
        assert ep is not None
        assert ep.status == "ready"
        chunks = await ChunkRepo(session).list_by_episode(ep_id)
        assert len(chunks) >= 2
        chunk_ids = [c.id for c in chunks]

    # --- P2: synth (mock Fish) ---
    from server.flows.tasks.p2_synth import run_p2_synth
    p2_results: list[P2Result] = []
    for cid in chunk_ids:
        result = await run_p2_synth(cid)
        p2_results.append(result)
    assert all(r.duration_s > 0 for r in p2_results)

    # Verify chunk status → synth_done
    async with maker() as session:
        for cid in chunk_ids:
            chunk = await ChunkRepo(session).get(cid)
            assert chunk is not None
            assert chunk.status == "synth_done"
            assert chunk.selected_take_id is not None

    # --- P3: transcribe (mock WhisperX) ---
    from server.flows.tasks.p3_transcribe import run_p3_transcribe
    p3_results: list[P3Result] = []
    for cid in chunk_ids:
        result = await run_p3_transcribe(cid, language="en")
        p3_results.append(result)
    assert all(r.word_count > 0 for r in p3_results)

    # Verify chunk status → transcribed
    async with maker() as session:
        for cid in chunk_ids:
            chunk = await ChunkRepo(session).get(cid)
            assert chunk is not None
            assert chunk.status == "transcribed"

    # Verify transcript in MinIO
    for cid in chunk_ids:
        key = chunk_transcript_key(ep_id, cid)
        assert await storage.exists(key)

    # --- P5: subtitles ---
    from server.flows.tasks.p5_subtitles import run_p5_subtitles
    p5_results: list[P5Result] = []
    for cid in chunk_ids:
        result = await run_p5_subtitles(cid)
        p5_results.append(result)

    # Verify SRT in MinIO
    for cid in chunk_ids:
        key = chunk_subtitle_key(ep_id, cid)
        assert await storage.exists(key)

    # --- P6: concat (real ffmpeg) ---
    from server.flows.tasks.p6_concat import run_p6_concat
    async with maker() as session:
        p6_result = await run_p6_concat(
            ep_id,
            padding_ms=100,
            shot_gap_ms=200,
            session=session,
            storage=storage,
        )
    assert p6_result.wav_uri != ""
    assert p6_result.srt_uri != ""
    assert p6_result.chunk_count >= 2

    # Verify final products in MinIO
    assert await storage.exists(final_wav_key(ep_id))
    assert await storage.exists(final_srt_key(ep_id))

    # Verify episode status → done
    async with maker() as session:
        ep = await EpisodeRepo(session).get(ep_id)
        assert ep is not None
        assert ep.status == "done"

    # Verify events table has stage_started/stage_finished chain
    async with maker() as session:
        event_repo = EventRepo(session)
        events = await event_repo.list_since(ep_id, after_id=0, limit=200)
        event_kinds = [e.kind for e in events]
        assert "stage_started" in event_kinds
        assert "stage_finished" in event_kinds
        # We expect multiple stage_started/finished pairs (P1, P2*N, P3*N, P5*N, P6)
        started_count = event_kinds.count("stage_started")
        finished_count = event_kinds.count("stage_finished")
        assert started_count >= 3  # at least P1 + some P2 + some P3
        assert finished_count >= 3


# ---------------------------------------------------------------------------
# Test: P2 failure — stage_failed event emitted
# ---------------------------------------------------------------------------


class FailingFishClient:
    """FishTTSClient that always fails."""

    async def synthesize(self, text: str, params: Any = None) -> bytes:
        raise RuntimeError("Simulated Fish API failure")

    async def aclose(self) -> None:
        pass


@pytest.mark.e2e
async def test_pipeline_p2_failure(storage: MinIOStorage, db_session: AsyncSession):
    """Test that a P2 failure writes a stage_failed event and raises."""
    ep_id = e2e_id()
    script_bytes = make_script_json("Failure Test", segments=[
        {"id": 1, "type": "hook", "text": "This will fail at P2."},
    ])

    maker = _get_maker()

    # Wire with failing fish client
    from server.flows.tasks.p2_synth import configure_p2_dependencies
    configure_p2_dependencies(
        session_factory=maker,
        storage=storage,
        fish_client_factory=lambda: FailingFishClient(),
    )

    await _create_episode_in_db(ep_id, "Failure Test", script_bytes, storage)

    # P1 should succeed
    ctx = P1Context(session_maker=maker, storage=storage)
    p1_result = await _run_p1(ctx, ep_id)
    assert len(p1_result.chunks) >= 1

    async with maker() as session:
        chunks = await ChunkRepo(session).list_by_episode(ep_id)
        chunk_id = chunks[0].id

    # P2 should fail
    from server.flows.tasks.p2_synth import run_p2_synth
    with pytest.raises(RuntimeError, match="Simulated Fish API failure"):
        await run_p2_synth(chunk_id)

    # Verify stage_failed event was written
    async with maker() as session:
        event_repo = EventRepo(session)
        events = await event_repo.list_since(ep_id, after_id=0, limit=200)
        failed_events = [e for e in events if e.kind == "stage_failed"]
        assert len(failed_events) >= 1
        assert failed_events[0].payload.get("stage") == "p2"
