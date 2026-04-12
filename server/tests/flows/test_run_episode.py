"""End-to-end tests for the run-episode flow.

These tests exercise the full P1 → P2 → P3 → P5 → P6 pipeline using:

- SQLite in-memory (real ORM).
- In-memory fake storage (FakeStorage).
- Mock httpx transport for whisperx-svc.
- Fake FishTTSClient.

We directly call the task body functions (run_p*) rather than going through
Prefect runtime, which lets us verify the orchestration logic without
needing a Prefect server.

Scenarios
---------
1. Happy path: full pipeline → episode.status == "done".
2. P2 failure (Fish error) → P2 raises, flow aborts.
3. P3 timeout → httpx.ReadTimeout, flow aborts.
"""

from __future__ import annotations

import io
import json
import shutil
import wave
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
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
    P1Result,
)
from server.core.fish_client import FishAuthError, FishTTSClient
from server.core.models import Base, Chunk, Episode, Event
from server.core.repositories import ChunkRepo, EpisodeRepo, EventRepo
from server.core.storage import (
    chunk_subtitle_key,
    chunk_take_key,
    chunk_transcript_key,
    episode_script_key,
    final_srt_key,
    final_wav_key,
)
from server.flows.tasks import p2_synth as p2_module
from server.flows.tasks import p2v_verify as p2v_module
from server.flows.tasks import p3_transcribe as p3_module
from server.flows.tasks import p5_subtitles as p5_module
from server.flows.tasks.p1_chunk import P1Context
from server.flows.tasks.p2_synth import configure_p2_dependencies, run_p2_synth
from server.flows.tasks.p2v_verify import (
    configure_p2v_dependencies,
    run_p2v_verify,
)
from server.flows.tasks.p3_transcribe import (
    configure_p3_dependencies,
    run_p3_transcribe,
)
from server.flows.tasks.p5_subtitles import (
    configure_p5_dependencies,
    run_p5_subtitles,
)
from server.flows.tasks.p6_concat import run_p6_concat

EP_ID = "ep-flow-test"

SAMPLE_SCRIPT = {
    "title": "Flow Test Episode",
    "segments": [
        {"id": 1, "type": "hook", "text": "你好世界，这是测试。"},
        {"id": 2, "type": "content", "text": "第二段内容在这里。"},
    ],
}

SAMPLE_TRANSCRIPT = {
    "transcript": [
        {"word": "你好", "start": 0.0, "end": 0.1, "score": 0.95},
        {"word": "世界", "start": 0.1, "end": 0.2, "score": 0.90},
        {"word": "这是", "start": 0.2, "end": 0.3, "score": 0.90},
        {"word": "测试", "start": 0.3, "end": 0.4, "score": 0.90},
        {"word": "内容", "start": 0.4, "end": 0.5, "score": 0.90},
    ],
    "language": "zh",
    "duration_s": 0.5,
    "model": "large-v3",
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

    async def upload_file(self, key: str, path: Path) -> str:
        self.objects[key] = Path(path).read_bytes()
        return self.s3_uri(key)

    async def download_bytes(self, key: str) -> bytes:
        if key not in self.objects:
            raise KeyError(f"object not found: {key}")
        return self.objects[key]

    async def exists(self, key: str) -> bool:
        return key in self.objects

    async def ensure_bucket(self) -> None:
        pass


class FakeFishClient:
    def __init__(
        self,
        *,
        wav_bytes: bytes | None = None,
        raise_exc: Exception | None = None,
    ) -> None:
        self._wav = wav_bytes if wav_bytes is not None else _make_tiny_wav()
        self._raise_exc = raise_exc
        self.calls: list[tuple[str, FishTTSParams]] = []

    async def synthesize(self, text: str, params: FishTTSParams) -> bytes:
        self.calls.append((text, params))
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._wav

    async def aclose(self) -> None:
        return None


def _mock_transport(
    status_code: int = 200,
    response_json: dict | None = None,
    raise_exc: Exception | None = None,
) -> httpx.MockTransport:
    async def handler(request: httpx.Request) -> httpx.Response:
        if raise_exc is not None:
            raise raise_exc
        body = response_json if response_json is not None else SAMPLE_TRANSCRIPT
        return httpx.Response(status_code=status_code, json=body)

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
    """Seed episode + upload script.json to fake storage."""
    async with session_factory() as session:
        await EpisodeRepo(session).create(
            EpisodeCreate(
                id=EP_ID,
                title="Flow Test",
                script_uri=f"s3://tts-harness/{episode_script_key(EP_ID)}",
            )
        )
        await session.commit()
    return session_factory


@pytest.fixture()
def storage() -> FakeStorage:
    s = FakeStorage()
    # Pre-load script.json.
    s.objects[episode_script_key(EP_ID)] = json.dumps(SAMPLE_SCRIPT).encode()
    return s


@pytest.fixture()
def fake_fish() -> FakeFishClient:
    return FakeFishClient()


@pytest.fixture(autouse=True)
def wire_all_deps(seeded, storage, fake_fish, monkeypatch):
    """Wire all task module DI globals."""
    monkeypatch.delenv("FISH_TTS_REFERENCE_ID", raising=False)
    monkeypatch.delenv("FISH_TTS_MODEL", raising=False)

    holder = {"client": fake_fish}

    def fish_factory():
        return holder["client"]

    configure_p2_dependencies(
        session_factory=seeded,
        storage=storage,
        fish_client_factory=fish_factory,
    )

    transport = _mock_transport()
    configure_p3_dependencies(
        session_factory=seeded,
        storage=storage,
        http_client_factory=lambda: httpx.AsyncClient(transport=transport),
        whisperx_url="http://test-whisperx:7860",
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

    # Clean up module globals.
    p2_module._session_factory = None
    p2_module._storage = None
    p2_module._fish_client_factory = None
    p2v_module._session_factory = None
    p2v_module._storage = None
    p2v_module._http_client_factory = None
    p3_module._session_factory = None
    p3_module._storage = None
    p3_module._http_client_factory = None
    p5_module._session_factory = None
    p5_module._storage = None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

ffmpeg_required = pytest.mark.skipif(
    shutil.which("ffmpeg") is None,
    reason="ffmpeg not in PATH — skipping flow integration test",
)


@ffmpeg_required
@pytest.mark.asyncio
async def test_happy_path_full_pipeline(seeded, storage, fake_fish):
    """Full P1 → P2 → P2v → P5 → P6 flow → episode.status == 'done'."""
    session_factory = seeded

    # P1: chunk the script.
    ctx = P1Context(session_maker=session_factory, storage=storage)
    from server.flows.tasks.p1_chunk import _run_p1

    p1_result = await _run_p1(ctx, EP_ID)
    chunk_ids = [c.id for c in p1_result.chunks]
    assert len(chunk_ids) >= 2

    # P2: synth each chunk.
    for cid in chunk_ids:
        await run_p2_synth(cid)

    # P2v: transcribe + verify each chunk.
    for cid in chunk_ids:
        await run_p2v_verify(cid, language="zh")

    # P5: subtitles for each chunk.
    for cid in chunk_ids:
        await run_p5_subtitles(cid)

    # Verify intermediate state.
    async with session_factory() as session:
        for cid in chunk_ids:
            chunk = await ChunkRepo(session).get(cid)
            # P5 sets "p5_done" (per A6 convention); we accept either.
            assert chunk.status in ("verified", "p5_done")

    # P6: concat.
    async with session_factory() as session:
        p6_result = await run_p6_concat(
            EP_ID,
            session=session,
            storage=storage,
            padding_ms=100,
            shot_gap_ms=200,
        )

    assert p6_result.episode_id == EP_ID
    assert p6_result.chunk_count >= 2
    assert p6_result.total_duration_s > 0

    # Episode should be "done".
    async with session_factory() as session:
        ep = await EpisodeRepo(session).get(EP_ID)
        assert ep.status == "done"

    # Final WAV and SRT should be in storage.
    assert final_wav_key(EP_ID) in storage.objects
    assert final_srt_key(EP_ID) in storage.objects


@pytest.mark.asyncio
async def test_p2_failure_aborts(seeded, storage):
    """P2 failure (FishAuthError) propagates — flow should abort."""
    session_factory = seeded

    # P1 first.
    ctx = P1Context(session_maker=session_factory, storage=storage)
    from server.flows.tasks.p1_chunk import _run_p1

    p1_result = await _run_p1(ctx, EP_ID)
    chunk_ids = [c.id for c in p1_result.chunks]

    # Reconfigure P2 with a failing fish client.
    bad_fish = FakeFishClient(raise_exc=FishAuthError("401 Unauthorized"))
    configure_p2_dependencies(
        session_factory=session_factory,
        storage=storage,
        fish_client_factory=lambda: bad_fish,
    )

    with pytest.raises(FishAuthError):
        await run_p2_synth(chunk_ids[0])

    # Chunk should still be pending.
    async with session_factory() as session:
        chunk = await ChunkRepo(session).get(chunk_ids[0])
        assert chunk.status == "pending"


@pytest.mark.asyncio
async def test_p2v_timeout_aborts(seeded, storage, fake_fish):
    """P2v timeout propagates — flow should abort after P2 succeeds."""
    session_factory = seeded

    # P1.
    ctx = P1Context(session_maker=session_factory, storage=storage)
    from server.flows.tasks.p1_chunk import _run_p1

    p1_result = await _run_p1(ctx, EP_ID)
    chunk_ids = [c.id for c in p1_result.chunks]

    # P2 succeeds.
    await run_p2_synth(chunk_ids[0])

    # Reconfigure P2v with timeout.
    transport = _mock_transport(raise_exc=httpx.ReadTimeout("timeout"))
    configure_p2v_dependencies(
        session_factory=session_factory,
        storage=storage,
        http_client_factory=lambda: httpx.AsyncClient(transport=transport),
        whisperx_url="http://test-whisperx:7860",
    )

    with pytest.raises(httpx.ReadTimeout):
        await run_p2v_verify(chunk_ids[0])

    # Chunk should still be synth_done.
    async with session_factory() as session:
        chunk = await ChunkRepo(session).get(chunk_ids[0])
        assert chunk.status == "synth_done"
