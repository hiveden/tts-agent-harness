"""Tests for ``server.flows.tasks.p2v_verify.run_p2v_verify``.

Scope
-----
- Real SQLAlchemy (SQLite in-memory) -- exercises repositories + events.
- Fake MinIO storage (in-memory dict).
- Mock httpx transport for whisperx-svc -- no network calls.

Scenarios
---------
1. P2v pass -- ASR matches, chunk.status -> verified, transcript uploaded.
2. P2v fail -- ratio too low (0.5), chunk.status stays synth_done, verify_failed Event.
3. P2v fail -- ratio too high (1.5), same behavior.
4. P2v boundary -- ratio exactly 0.7, should pass.
5. P2v boundary -- ratio exactly 1.3, should pass.
6. P2v -- control markers stripped ([break] not in ratio calc).
7. P2v -- take not found raises DomainError.
8. P2v -- Event write verification (verify_started + verify_finished or verify_failed).
"""

from __future__ import annotations

import io
import json
import wave
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
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
    TakeAppend,
)
from server.core.models import Base, Chunk, Event
from server.core.repositories import (
    ChunkRepo,
    EpisodeRepo,
    EventRepo,
    TakeRepo,
)
from server.core.storage import chunk_take_key, chunk_transcript_key
from server.flows.tasks import p2v_verify as p2v_module
from server.flows.tasks.p2v_verify import (
    configure_p2v_dependencies,
    run_p2v_verify,
)

EP_ID = "ep-verify"
CHUNK_ID = "ep-verify:c1"
TAKE_ID = "take-001"


def _make_transcript(text: str) -> dict[str, Any]:
    """Build a WhisperX transcript JSON with one word per char."""
    words = []
    t = 0.0
    for ch in text:
        if ch.strip():
            words.append({"word": ch, "start": t, "end": t + 0.25, "score": 0.9})
            t += 0.25
    return {
        "transcript": words,
        "language": "zh",
        "duration_s": t,
        "model": "large-v3",
    }


# Default: ASR returns same text as original.
ORIGINAL_TEXT = "你好世界"
SAMPLE_TRANSCRIPT = _make_transcript(ORIGINAL_TEXT)


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
            raise KeyError(key)
        return self.objects[key]


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
    maker = async_sessionmaker(engine, expire_on_commit=False)
    yield maker


async def _seed(session_factory, *, text: str = ORIGINAL_TEXT):
    """Seed one episode + one synth_done chunk with a take."""
    async with session_factory() as session:
        await EpisodeRepo(session).create(
            EpisodeCreate(
                id=EP_ID,
                title="Verify Test",
                script_uri="s3://tts-harness/episodes/ep-verify/script.json",
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
                    text=text,
                    text_normalized=text,
                    char_count=len(text),
                )
            ]
        )
        await TakeRepo(session).append(
            TakeAppend(
                id=TAKE_ID,
                chunk_id=CHUNK_ID,
                audio_uri=f"s3://tts-harness/{chunk_take_key(EP_ID, CHUNK_ID, TAKE_ID)}",
                duration_s=0.5,
            )
        )
        await chunk_repo.set_selected_take(CHUNK_ID, TAKE_ID)
        await chunk_repo.set_status(CHUNK_ID, "synth_done")
        await session.commit()
    return session_factory


@pytest_asyncio.fixture()
async def seeded(session_factory):
    return await _seed(session_factory)


@pytest.fixture()
def storage() -> FakeStorage:
    s = FakeStorage()
    wav_key = chunk_take_key(EP_ID, CHUNK_ID, TAKE_ID)
    s.objects[wav_key] = _make_tiny_wav()
    return s


@pytest.fixture(autouse=True)
def wire_p2v_deps(seeded, storage):
    transport = _mock_transport()
    client_factory = lambda: httpx.AsyncClient(transport=transport)

    configure_p2v_dependencies(
        session_factory=seeded,
        storage=storage,
        http_client_factory=client_factory,
        whisperx_url="http://test-whisperx:7860",
    )
    yield
    p2v_module._session_factory = None
    p2v_module._storage = None
    p2v_module._http_client_factory = None


@pytest_asyncio.fixture()
async def fresh_engine():
    """Independent engine for tests that need custom seed data."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture()
async def fresh_session_factory(fresh_engine) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    maker = async_sessionmaker(fresh_engine, expire_on_commit=False)
    yield maker


# ---------------------------------------------------------------------------
# 1. P2v pass — ASR matches, chunk.status -> verified
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pass_happy_path(seeded, storage):
    """P2v pass: synth_done -> verified, transcript uploaded."""
    result = await run_p2v_verify(CHUNK_ID, language="zh")

    assert result.chunk_id == CHUNK_ID
    assert result.verdict == "pass"
    assert 0.7 <= result.char_ratio <= 1.3
    assert result.transcript_uri is not None
    assert "transcript.json" in result.transcript_uri

    # Transcript in storage.
    transcript_key = chunk_transcript_key(EP_ID, CHUNK_ID)
    assert transcript_key in storage.objects

    # Chunk status -> verified.
    async with seeded() as session:
        chunk = await ChunkRepo(session).get(CHUNK_ID)
        assert chunk.status == "verified"


# ---------------------------------------------------------------------------
# 2. P2v fail — ratio too low (0.5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fail_ratio_low(seeded, storage):
    """P2v fail: ratio ~0.5, chunk stays synth_done, verify_failed Event."""
    # ASR returns half the chars.
    short_transcript = _make_transcript("你好")  # 2 chars vs 4 original
    transport = _mock_transport(response_json=short_transcript)
    configure_p2v_dependencies(
        session_factory=seeded,
        storage=storage,
        http_client_factory=lambda: httpx.AsyncClient(transport=transport),
        whisperx_url="http://test-whisperx:7860",
    )

    result = await run_p2v_verify(CHUNK_ID, language="zh")

    assert result.verdict == "fail"
    assert result.char_ratio == 0.5

    async with seeded() as session:
        chunk = await ChunkRepo(session).get(CHUNK_ID)
        assert chunk.status == "synth_done"


# ---------------------------------------------------------------------------
# 3. P2v fail — ratio too high (1.5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fail_ratio_high(seeded, storage):
    """P2v fail: ratio ~1.5, chunk stays synth_done."""
    long_transcript = _make_transcript("你好世界再见")  # 6 chars vs 4 original
    transport = _mock_transport(response_json=long_transcript)
    configure_p2v_dependencies(
        session_factory=seeded,
        storage=storage,
        http_client_factory=lambda: httpx.AsyncClient(transport=transport),
        whisperx_url="http://test-whisperx:7860",
    )

    result = await run_p2v_verify(CHUNK_ID, language="zh")

    assert result.verdict == "fail"
    assert result.char_ratio == 1.5

    async with seeded() as session:
        chunk = await ChunkRepo(session).get(CHUNK_ID)
        assert chunk.status == "synth_done"


# ---------------------------------------------------------------------------
# 4. P2v boundary — ratio exactly 0.7, should pass
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_boundary_ratio_low(fresh_session_factory, storage):
    """P2v boundary: ratio = 0.7 exactly should pass."""
    # 10-char original, 7-char ASR -> ratio 0.7
    original = "一二三四五六七八九十"  # 10 chars
    asr_text = "一二三四五六七"  # 7 chars
    sf = await _seed(fresh_session_factory, text=original)

    transcript = _make_transcript(asr_text)
    transport = _mock_transport(response_json=transcript)
    configure_p2v_dependencies(
        session_factory=sf,
        storage=storage,
        http_client_factory=lambda: httpx.AsyncClient(transport=transport),
        whisperx_url="http://test-whisperx:7860",
    )

    result = await run_p2v_verify(CHUNK_ID, language="zh")

    assert result.verdict == "pass"
    assert result.char_ratio == 0.7

    async with sf() as session:
        chunk = await ChunkRepo(session).get(CHUNK_ID)
        assert chunk.status == "verified"


# ---------------------------------------------------------------------------
# 5. P2v boundary — ratio exactly 1.3, should pass
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_boundary_ratio_high(fresh_session_factory, storage):
    """P2v boundary: ratio = 1.3 exactly should pass."""
    # 10-char original, 13-char ASR -> ratio 1.3
    original = "一二三四五六七八九十"  # 10 chars
    asr_text = "一二三四五六七八九十再见了"  # 13 chars
    sf = await _seed(fresh_session_factory, text=original)

    transcript = _make_transcript(asr_text)
    transport = _mock_transport(response_json=transcript)
    configure_p2v_dependencies(
        session_factory=sf,
        storage=storage,
        http_client_factory=lambda: httpx.AsyncClient(transport=transport),
        whisperx_url="http://test-whisperx:7860",
    )

    result = await run_p2v_verify(CHUNK_ID, language="zh")

    assert result.verdict == "pass"
    assert result.char_ratio == 1.3

    async with sf() as session:
        chunk = await ChunkRepo(session).get(CHUNK_ID)
        assert chunk.status == "verified"


# ---------------------------------------------------------------------------
# 6. P2v — control markers stripped before ratio calc
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_control_markers_stripped(fresh_session_factory, storage):
    """[break] and other control markers are stripped before char_ratio calc."""
    original_with_markers = "你好 [break] 世界"  # stripped = "你好 世界" -> 4 non-space chars
    sf = await _seed(fresh_session_factory, text=original_with_markers)

    # ASR returns the 4 actual chars.
    transcript = _make_transcript("你好世界")
    transport = _mock_transport(response_json=transcript)
    configure_p2v_dependencies(
        session_factory=sf,
        storage=storage,
        http_client_factory=lambda: httpx.AsyncClient(transport=transport),
        whisperx_url="http://test-whisperx:7860",
    )

    result = await run_p2v_verify(CHUNK_ID, language="zh")

    assert result.verdict == "pass"
    # Ratio should be 1.0 (4 chars / 4 chars after strip + whitespace removal).
    assert result.char_ratio == 1.0


# ---------------------------------------------------------------------------
# 7. P2v — take not found raises DomainError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_take_wav_missing(seeded, storage):
    """Take WAV missing from storage raises DomainError('not_found')."""
    storage.objects.clear()

    with pytest.raises(DomainError, match="take WAV missing"):
        await run_p2v_verify(CHUNK_ID)


# ---------------------------------------------------------------------------
# 8. P2v — Event write verification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_events_written_on_pass(seeded, storage):
    """verify_started + verify_finished events written on pass."""
    await run_p2v_verify(CHUNK_ID, language="zh")

    async with seeded() as session:
        events = await EventRepo(session).list_since(EP_ID)
        kinds = [e.kind for e in events]
        assert "verify_started" in kinds
        assert "verify_finished" in kinds
        assert "verify_failed" not in kinds


@pytest.mark.asyncio
async def test_events_written_on_fail(seeded, storage):
    """verify_started + verify_failed events written on fail."""
    short_transcript = _make_transcript("你")  # 1 char vs 4 original -> ratio 0.25
    transport = _mock_transport(response_json=short_transcript)
    configure_p2v_dependencies(
        session_factory=seeded,
        storage=storage,
        http_client_factory=lambda: httpx.AsyncClient(transport=transport),
        whisperx_url="http://test-whisperx:7860",
    )

    result = await run_p2v_verify(CHUNK_ID, language="zh")
    assert result.verdict == "fail"

    async with seeded() as session:
        events = await EventRepo(session).list_since(EP_ID)
        kinds = [e.kind for e in events]
        assert "verify_started" in kinds
        assert "verify_failed" in kinds

        # verify_failed event should contain diagnostic payload.
        fail_events = [e for e in events if e.kind == "verify_failed"]
        assert len(fail_events) >= 1
        payload = fail_events[0].payload
        assert "char_ratio" in payload
        assert "original_text" in payload
        assert "transcribed_text" in payload
