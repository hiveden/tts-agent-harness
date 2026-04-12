"""Integration-ish tests for the P5 Prefect task body.

We exercise :func:`run_p5_subtitles` directly (skipping the Prefect
runtime) against:

- SQLite in-memory session factory (real ORM + real repositories).
- An in-process fake MinIO storage — tiny dict-backed implementation of
  the ``upload_bytes`` / ``download_bytes`` surface P5 actually uses.

This mirrors the shape A2 already uses for repository tests and keeps the
suite fast & hermetic (no docker, no prefect worker).
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from server.core.domain import (
    ChunkInput,
    DomainError,
    EpisodeCreate,
    TakeAppend,
)
from server.core.models import Base
from server.core.repositories import (
    ChunkRepo,
    EpisodeRepo,
    EventRepo,
    TakeRepo,
)
from server.core.storage import chunk_subtitle_key, chunk_transcript_key
from server.flows.tasks import p5_subtitles as p5_module
from server.flows.tasks.p5_subtitles import (
    configure_p5_dependencies,
    run_p5_subtitles,
)


# ---------------------------------------------------------------------------
# In-memory fake storage (just the shape P5 uses)
# ---------------------------------------------------------------------------


@dataclass
class FakeStorage:
    bucket: str = "tts-harness"
    objects: dict[str, bytes] = field(default_factory=dict)

    def s3_uri(self, key: str) -> str:
        return f"s3://{self.bucket}/{key}"

    async def upload_bytes(
        self,
        key: str,
        data: bytes,
        content_type: str | None = None,
    ) -> str:
        self.objects[key] = data
        return self.s3_uri(key)

    async def download_bytes(self, key: str) -> bytes:
        if key not in self.objects:
            raise KeyError(key)
        return self.objects[key]


# ---------------------------------------------------------------------------
# Session factory bound to a per-test SQLite engine
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture()
async def session_factory(engine):
    maker = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def _factory() -> AsyncIterator[AsyncSession]:
        async with maker() as sess:
            yield sess

    return _factory


@pytest_asyncio.fixture()
async def storage():
    return FakeStorage()


@pytest_asyncio.fixture(autouse=True)
async def wire_deps(session_factory, storage):
    """Reset + inject p5 module deps per test.

    ``autouse`` because every test in this file needs this wiring, and
    forgetting it would produce a ``RuntimeError("not configured")``.
    """
    configure_p5_dependencies(session_factory=session_factory, storage=storage)
    yield
    # Best-effort reset so leaked state never crosses tests.
    p5_module._session_factory = None
    p5_module._storage = None


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


EP_ID = "ep-p5"
CHUNK_ID = "ep-p5:shot01:0"
TAKE_ID = "tk-001"


async def _seed_chunk(
    session_factory,
    *,
    chunk_text: str = "你好。世界！",
    subtitle_text: str | None = None,
    duration_s: float = 4.0,
    with_take: bool = True,
    select_take: bool = True,
) -> None:
    async with session_factory() as session:
        ep_repo = EpisodeRepo(session)
        await ep_repo.create(
            EpisodeCreate(
                id=EP_ID,
                title="P5 test",
                script_uri=f"s3://bucket/episodes/{EP_ID}/script.json",
            )
        )
        chunk_repo = ChunkRepo(session)
        await chunk_repo.bulk_insert(
            [
                ChunkInput(
                    id=CHUNK_ID,
                    episode_id=EP_ID,
                    shot_id="shot01",
                    idx=0,
                    text=chunk_text,
                    text_normalized=chunk_text,
                    subtitle_text=subtitle_text,
                    char_count=len(chunk_text),
                )
            ]
        )
        if with_take:
            await TakeRepo(session).append(
                TakeAppend(
                    id=TAKE_ID,
                    chunk_id=CHUNK_ID,
                    audio_uri=f"s3://bucket/episodes/{EP_ID}/chunks/{CHUNK_ID}/takes/{TAKE_ID}.wav",
                    duration_s=duration_s,
                )
            )
            if select_take:
                await chunk_repo.set_selected_take(CHUNK_ID, TAKE_ID)
            await chunk_repo.set_status(CHUNK_ID, "verified")
        await session.commit()


async def _put_transcript(storage: FakeStorage, words: list[dict]) -> None:
    payload = {
        "transcript": words,
        "language": "zh",
        "duration_s": sum((w["end"] - w["start"] for w in words), 0.0),
        "model": "large-v3",
    }
    storage.objects[chunk_transcript_key(EP_ID, CHUNK_ID)] = json.dumps(
        payload, ensure_ascii=False
    ).encode("utf-8")


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestRunP5SubtitlesHappyPath:
    async def test_writes_srt_and_flips_status(self, session_factory, storage):
        await _seed_chunk(session_factory, chunk_text="你好。世界！", duration_s=4.0)
        await _put_transcript(
            storage,
            [
                {"word": "你好", "start": 0.0, "end": 2.0, "score": 0.9},
                {"word": "世界", "start": 2.0, "end": 4.0, "score": 0.9},
            ],
        )

        result = await run_p5_subtitles(CHUNK_ID)

        # Return value
        assert result.chunk_id == CHUNK_ID
        assert result.line_count == 2
        expected_key = chunk_subtitle_key(EP_ID, CHUNK_ID)
        assert result.subtitle_uri.endswith(expected_key)

        # MinIO holds the SRT bytes at the canonical key
        assert expected_key in storage.objects
        srt_bytes = storage.objects[expected_key]
        srt = srt_bytes.decode("utf-8")
        assert srt.startswith("1\n00:00:00,000 --> ")
        assert "你好。" in srt
        assert "世界！" in srt
        # Two cues → two sequence numbers
        assert "\n2\n" in srt

        # DB side-effects
        async with session_factory() as session:
            chunk = await ChunkRepo(session).get(CHUNK_ID)
            assert chunk is not None
            assert chunk.status == "verified"  # P5 no longer changes status

            events = await EventRepo(session).list_since(EP_ID)
            kinds = [e.kind for e in events]
            assert "stage_started" in kinds
            assert "stage_finished" in kinds
            # The finished event carries the line count.
            finished = [e for e in events if e.kind == "stage_finished"][-1]
            assert finished.payload["stage"] == "p5"
            assert finished.payload["line_count"] == 2

    async def test_prefers_subtitle_text_over_text(self, session_factory, storage):
        await _seed_chunk(
            session_factory,
            chunk_text="主文本。",
            subtitle_text="字幕覆盖文本一。字幕覆盖文本二！",
            duration_s=5.0,
        )
        await _put_transcript(
            storage,
            [{"word": "主文本", "start": 0.0, "end": 5.0, "score": 1.0}],
        )

        result = await run_p5_subtitles(CHUNK_ID)

        assert result.line_count == 2
        srt = storage.objects[chunk_subtitle_key(EP_ID, CHUNK_ID)].decode("utf-8")
        assert "字幕覆盖文本一。" in srt
        assert "主文本" not in srt  # the non-subtitle field is ignored

    async def test_determinism_same_input_same_srt(self, session_factory, storage):
        await _seed_chunk(session_factory, chunk_text="一。二。三。", duration_s=3.0)
        await _put_transcript(
            storage,
            [{"word": "一二三", "start": 0.0, "end": 3.0, "score": 1.0}],
        )
        r1 = await run_p5_subtitles(CHUNK_ID)
        first = storage.objects[chunk_subtitle_key(EP_ID, CHUNK_ID)]

        # Re-run: seed state is the same (chunk row still there), transcript
        # still there.  Clear the uploaded object so we can prove it is
        # re-written byte-for-byte identical.
        del storage.objects[chunk_subtitle_key(EP_ID, CHUNK_ID)]
        r2 = await run_p5_subtitles(CHUNK_ID)
        second = storage.objects[chunk_subtitle_key(EP_ID, CHUNK_ID)]

        assert r1.line_count == r2.line_count
        assert first == second


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------


class TestRunP5SubtitlesFailures:
    async def test_chunk_missing_raises_not_found(self, session_factory, storage):
        with pytest.raises(DomainError) as exc_info:
            await run_p5_subtitles("nope:shot01:0")
        assert exc_info.value.code == "not_found"

    async def test_missing_selected_take(self, session_factory, storage):
        await _seed_chunk(
            session_factory,
            chunk_text="你好。",
            with_take=False,
            select_take=False,
        )
        with pytest.raises(DomainError) as exc_info:
            await run_p5_subtitles(CHUNK_ID)
        assert exc_info.value.code == "invalid_state"

    async def test_transcript_missing(self, session_factory, storage):
        await _seed_chunk(session_factory, chunk_text="你好。", duration_s=2.0)
        # No transcript uploaded.
        with pytest.raises(DomainError) as exc_info:
            await run_p5_subtitles(CHUNK_ID)
        assert exc_info.value.code == "not_found"

        # stage_failed event emitted.
        async with session_factory() as session:
            events = await EventRepo(session).list_since(EP_ID)
            kinds = [e.kind for e in events]
            assert "stage_failed" in kinds

    async def test_transcript_empty_words(self, session_factory, storage):
        await _seed_chunk(session_factory, chunk_text="你好。", duration_s=2.0)
        await _put_transcript(storage, [])  # empty list
        with pytest.raises(DomainError) as exc_info:
            await run_p5_subtitles(CHUNK_ID)
        assert exc_info.value.code == "invalid_state"

    async def test_all_control_markers_invalid_input(self, session_factory, storage):
        await _seed_chunk(
            session_factory,
            chunk_text="[break][long break]",
            duration_s=1.0,
        )
        await _put_transcript(
            storage,
            [{"word": "", "start": 0.0, "end": 1.0, "score": 0.1}],
        )
        with pytest.raises(DomainError) as exc_info:
            await run_p5_subtitles(CHUNK_ID)
        assert exc_info.value.code == "invalid_input"
