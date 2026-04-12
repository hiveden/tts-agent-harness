"""Tests for the retry-chunk-stage mini flow.

Scenarios
---------
1. cascade=True: from P2 → runs P2 + P2v + P5.
2. cascade=False: from P2 → runs only P2, marks P2v/P5 stage_runs as stale.
"""

from __future__ import annotations

import io
import json
import wave
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator

import httpx
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
    FishTTSParams,
    TakeAppend,
)
from server.core.models import Base, Chunk
from server.core.repositories import (
    ChunkRepo,
    EpisodeRepo,
    StageRunRepo,
    TakeRepo,
)
from server.flows.tasks import p2_synth as p2_module
from server.flows.tasks import p2v_verify as p2v_module
from server.flows.tasks import p5_subtitles as p5_module
from server.flows.tasks.p2_synth import configure_p2_dependencies, run_p2_synth
from server.flows.tasks.p2v_verify import (
    configure_p2v_dependencies,
    run_p2v_verify,
)
from server.flows.tasks.p5_subtitles import (
    configure_p5_dependencies,
    run_p5_subtitles,
)
from server.flows.retry_chunk import CHUNK_STAGES, _mark_downstream_stale
from server.core.storage import chunk_take_key, chunk_transcript_key

EP_ID = "ep-retry"
CHUNK_ID = "ep-retry:c1"

SAMPLE_TRANSCRIPT = {
    "transcript": [
        {"word": "你好", "start": 0.0, "end": 0.3, "score": 0.95},
        {"word": "世界", "start": 0.3, "end": 0.5, "score": 0.90},
    ],
    "language": "zh",
    "duration_s": 0.5,
}


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


def _make_tiny_wav(seconds: float = 0.5, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        n = int(rate * seconds)
        wf.writeframes(b"\x00\x00" * n)
    return buf.getvalue()


@dataclass
class FakeStorage:
    bucket: str = "tts-harness"
    objects: dict[str, bytes] = field(default_factory=dict)

    def s3_uri(self, key: str) -> str:
        return f"s3://{self.bucket}/{key}"

    async def upload_bytes(
        self, key: str, data: bytes, content_type: str | None = None
    ) -> str:
        self.objects[key] = data
        return self.s3_uri(key)

    async def download_bytes(self, key: str) -> bytes:
        if key not in self.objects:
            raise KeyError(f"object not found: {key}")
        return self.objects[key]


class FakeFishClient:
    def __init__(self) -> None:
        self._wav = _make_tiny_wav()
        self.calls: list = []

    async def synthesize(self, text: str, params: FishTTSParams) -> bytes:
        self.calls.append((text, params))
        return self._wav

    async def aclose(self) -> None:
        pass


def _mock_transport() -> httpx.MockTransport:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=200, json=SAMPLE_TRANSCRIPT)

    return httpx.MockTransport(handler)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture()
async def session_factory(engine) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    yield async_sessionmaker(engine, expire_on_commit=False)


@pytest_asyncio.fixture()
async def seeded(session_factory):
    """Episode + one pending chunk."""
    async with session_factory() as session:
        await EpisodeRepo(session).create(
            EpisodeCreate(
                id=EP_ID,
                title="Retry Test",
                script_uri="s3://tts-harness/episodes/ep-retry/script.json",
            )
        )
        await ChunkRepo(session).bulk_insert(
            [
                ChunkInput(
                    id=CHUNK_ID,
                    episode_id=EP_ID,
                    shot_id="shot01",
                    idx=0,
                    text="你好世界",
                    text_normalized="你好世界",
                    char_count=4,
                )
            ]
        )
        await session.commit()
    return session_factory


@pytest.fixture()
def storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture()
def fake_fish() -> FakeFishClient:
    return FakeFishClient()


@pytest.fixture(autouse=True)
def wire_deps(seeded, storage, fake_fish, monkeypatch):
    monkeypatch.delenv("FISH_TTS_REFERENCE_ID", raising=False)
    monkeypatch.delenv("FISH_TTS_MODEL", raising=False)

    configure_p2_dependencies(
        session_factory=seeded,
        storage=storage,
        fish_client_factory=lambda: fake_fish,
    )
    configure_p2v_dependencies(
        session_factory=seeded,
        storage=storage,
        http_client_factory=lambda: httpx.AsyncClient(transport=_mock_transport()),
        whisperx_url="http://test-whisperx:7860",
    )
    configure_p5_dependencies(
        session_factory=seeded,
        storage=storage,
    )
    yield
    p2_module._session_factory = None
    p2_module._storage = None
    p2_module._fish_client_factory = None
    p2v_module._session_factory = None
    p2v_module._storage = None
    p2v_module._http_client_factory = None
    p5_module._session_factory = None
    p5_module._storage = None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cascade_true_from_p2(seeded, storage):
    """cascade=True from P2: runs P2 → P3 → P5 in sequence."""
    # Run P2.
    p2_result = await run_p2_synth(CHUNK_ID)
    assert p2_result.chunk_id == CHUNK_ID

    async with seeded() as session:
        chunk = await ChunkRepo(session).get(CHUNK_ID)
        assert chunk.status == "synth_done"

    # Run P2v.
    p2v_result = await run_p2v_verify(CHUNK_ID, language="zh")
    assert p2v_result.chunk_id == CHUNK_ID

    async with seeded() as session:
        chunk = await ChunkRepo(session).get(CHUNK_ID)
        assert chunk.status == "verified"

    # Run P5.
    p5_result = await run_p5_subtitles(CHUNK_ID)
    assert p5_result.chunk_id == CHUNK_ID


@pytest.mark.asyncio
async def test_cascade_false_marks_stale(seeded, storage):
    """cascade=False from P2: only runs P2, then marks P3/P5 as stale."""
    # First do a full run so stage_runs exist for P3/P5.
    await run_p2_synth(CHUNK_ID)
    await run_p2v_verify(CHUNK_ID)
    await run_p5_subtitles(CHUNK_ID)

    # Create stage_run records for P2v and P5.
    async with seeded() as session:
        repo = StageRunRepo(session)
        await repo.upsert(chunk_id=CHUNK_ID, stage="p2v", status="ok")
        await repo.upsert(chunk_id=CHUNK_ID, stage="p5", status="ok")
        await session.commit()

    # Now simulate cascade=False retry from P2.
    # Run only P2.
    await run_p2_synth(CHUNK_ID)

    # Mark downstream as stale.
    downstream = CHUNK_STAGES[CHUNK_STAGES.index("p2") + 1:]
    await _mark_downstream_stale(CHUNK_ID, downstream)

    # Verify P2v and P5 stage_runs are marked stale.
    async with seeded() as session:
        repo = StageRunRepo(session)
        p2v_run = await repo.get(CHUNK_ID, "p2v")
        assert p2v_run is not None
        assert p2v_run.stale is True
        p5_run = await repo.get(CHUNK_ID, "p5")
        assert p5_run is not None
        assert p5_run.stale is True
