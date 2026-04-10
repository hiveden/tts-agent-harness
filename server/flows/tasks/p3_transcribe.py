"""P3 — WhisperX transcription, Prefect task.

Per ADR-001 §4.8, P3 does NOT import WhisperX directly — instead it HTTP-
calls the ``whisperx-svc`` container at ``/transcribe``. The task downloads
the selected take's WAV from MinIO, POSTs it as multipart to WhisperX,
persists the transcript JSON back to MinIO, and transitions chunk status
to ``transcribed``.

Per-call lifecycle
------------------
1. Load chunk + selected take from DB. Validate preconditions.
2. Write a ``stage_started`` event (fires pg_notify → SSE).
3. Download the take WAV from MinIO.
4. POST multipart (file=WAV, language=episode language) to whisperx-svc.
5. Upload transcript JSON to MinIO under ``chunk_transcript_key``.
6. In a single transaction:

   - ``chunks.status`` → ``transcribed``
   - ``stage_finished`` event

7. Return :class:`P3Result`.

Failure paths
-------------
- Chunk missing                      → ``DomainError("not_found")``, fatal.
- Chunk missing ``selected_take_id`` → ``DomainError("invalid_state")``, fatal.
- Take WAV missing from MinIO        → ``DomainError("not_found")``, fatal.
- WhisperX 5xx / timeout             → let Prefect retry via ``retries=5``.
- WhisperX returns empty transcript  → ``DomainError("invalid_state")``.
- MinIO upload failure               → raise, Prefect retries.

On any failure after ``stage_started`` the task best-effort writes a
``stage_failed`` event and re-raises so Prefect's retry policy kicks in.
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable

import httpx
from prefect import task
from sqlalchemy.ext.asyncio import AsyncSession

from server.core.domain import (
    DomainError,
    P3Result,
    WhisperXTranscript,
)
from server.core.events import write_event
from server.core.repositories import ChunkRepo, TakeRepo
from server.core.storage import (
    MinIOStorage,
    chunk_take_key,
    chunk_transcript_key,
)

log = logging.getLogger(__name__)

# Default whisperx-svc endpoint.
DEFAULT_WHISPERX_URL = os.environ.get("WHISPERX_URL", "http://localhost:7860")


# ---------------------------------------------------------------------------
# Dependency wiring (mirrors p2_synth / p5_subtitles pattern)
# ---------------------------------------------------------------------------

_SessionFactory = Callable[[], Any]  # returns an async ctx manager → AsyncSession

_session_factory: _SessionFactory | None = None
_storage: MinIOStorage | None = None
_http_client_factory: Callable[[], httpx.AsyncClient] | None = None
_whisperx_url: str = DEFAULT_WHISPERX_URL


def configure_p3_dependencies(
    *,
    session_factory: _SessionFactory,
    storage: MinIOStorage,
    http_client_factory: Callable[[], httpx.AsyncClient] | None = None,
    whisperx_url: str = DEFAULT_WHISPERX_URL,
) -> None:
    """Inject process-wide dependencies for the p3_transcribe task.

    Called once at worker startup (real runtime) or from test fixtures.

    Parameters
    ----------
    session_factory
        Callable that returns an async context manager yielding AsyncSession.
    storage
        MinIO storage wrapper for downloading WAV / uploading transcript.
    http_client_factory
        Optional factory for ``httpx.AsyncClient``. If ``None``, a default
        client is created per call. Tests inject a mock-transport client.
    whisperx_url
        Base URL of the whisperx-svc HTTP service.
    """
    global _session_factory, _storage, _http_client_factory, _whisperx_url
    _session_factory = session_factory
    _storage = storage
    _http_client_factory = http_client_factory
    _whisperx_url = whisperx_url


def _require_deps() -> tuple[_SessionFactory, MinIOStorage]:
    if _session_factory is None or _storage is None:
        raise RuntimeError(
            "p3_transcribe dependencies not configured. "
            "Call configure_p3_dependencies(...) before running the task."
        )
    return _session_factory, _storage


def _get_http_client() -> httpx.AsyncClient:
    """Return an httpx client — injected or default."""
    if _http_client_factory is not None:
        return _http_client_factory()
    return httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0))


@asynccontextmanager
async def _session_scope(factory: _SessionFactory) -> AsyncIterator[AsyncSession]:
    ctx = factory()
    async with ctx as session:  # type: ignore[misc]
        yield session


# ---------------------------------------------------------------------------
# Core routine (testable without Prefect runtime)
# ---------------------------------------------------------------------------


async def run_p3_transcribe(
    chunk_id: str,
    *,
    language: str = "zh",
) -> P3Result:
    """Pure coroutine body of the P3 task.

    Split out from the Prefect ``@task`` wrapper so unit tests can call
    it directly without spinning up a Prefect task runner.
    """
    session_factory, storage = _require_deps()

    # 1. Load chunk + take, validate preconditions.
    async with _session_scope(session_factory) as session:
        chunk = await ChunkRepo(session).get(chunk_id)
        if chunk is None:
            raise DomainError("not_found", f"chunk not found: {chunk_id}")
        if not chunk.selected_take_id:
            raise DomainError(
                "invalid_state",
                f"chunk {chunk_id} has no selected_take_id",
            )
        take = await TakeRepo(session).select(chunk.selected_take_id)
        if take is None:
            raise DomainError(
                "invalid_state",
                f"selected take {chunk.selected_take_id} not found for chunk {chunk_id}",
            )
        episode_id = chunk.episode_id
        take_id = take.id

        # 2. stage_started event.
        started_at = datetime.now(timezone.utc)
        await write_event(
            session,
            episode_id=episode_id,
            chunk_id=chunk_id,
            kind="stage_started",
            payload={
                "stage": "p3",
                "started_at": started_at.isoformat(),
            },
        )
        await session.commit()

    # 3. Download take WAV from MinIO (outside DB tx).
    wav_key = chunk_take_key(episode_id, chunk_id, take_id)
    try:
        wav_bytes = await storage.download_bytes(wav_key)
    except Exception as exc:
        await _emit_stage_failed(
            session_factory,
            episode_id=episode_id,
            chunk_id=chunk_id,
            error=f"take WAV download failed: {type(exc).__name__}: {exc}",
        )
        raise DomainError(
            "not_found",
            f"take WAV missing for chunk {chunk_id}: {wav_key}",
        ) from exc

    if not wav_bytes:
        await _emit_stage_failed(
            session_factory,
            episode_id=episode_id,
            chunk_id=chunk_id,
            error="take WAV is zero bytes",
        )
        raise DomainError("invalid_state", f"take WAV is empty for chunk {chunk_id}")

    # 4. POST to whisperx-svc.
    client = _get_http_client()
    try:
        transcript_data = await _call_whisperx(client, wav_bytes, language)
    except Exception as exc:
        await _emit_stage_failed(
            session_factory,
            episode_id=episode_id,
            chunk_id=chunk_id,
            error=f"whisperx call failed: {type(exc).__name__}: {exc}",
        )
        raise
    finally:
        await client.aclose()

    # Validate transcript structure.
    try:
        transcript = WhisperXTranscript.model_validate(transcript_data)
    except Exception as exc:
        await _emit_stage_failed(
            session_factory,
            episode_id=episode_id,
            chunk_id=chunk_id,
            error=f"transcript validation failed: {exc}",
        )
        raise DomainError(
            "invalid_state", f"transcript validation failed: {exc}"
        ) from exc

    word_count = len(transcript.transcript)

    # 5. Upload transcript JSON to MinIO.
    transcript_key = chunk_transcript_key(episode_id, chunk_id)
    transcript_json = json.dumps(transcript_data, ensure_ascii=False).encode("utf-8")
    try:
        transcript_uri = await storage.upload_bytes(
            transcript_key,
            transcript_json,
            content_type="application/json",
        )
    except Exception as exc:
        await _emit_stage_failed(
            session_factory,
            episode_id=episode_id,
            chunk_id=chunk_id,
            error=f"transcript upload failed: {exc}",
        )
        raise

    # 6. Persist state + stage_finished event.
    async with _session_scope(session_factory) as session:
        await ChunkRepo(session).set_status(chunk_id, "transcribed")
        finished_at = datetime.now(timezone.utc)
        await write_event(
            session,
            episode_id=episode_id,
            chunk_id=chunk_id,
            kind="stage_finished",
            payload={
                "stage": "p3",
                "transcript_uri": transcript_uri,
                "word_count": word_count,
                "finished_at": finished_at.isoformat(),
            },
        )
        await session.commit()

    return P3Result(
        chunk_id=chunk_id,
        transcript_uri=transcript_uri,
        word_count=word_count,
    )


async def _call_whisperx(
    client: httpx.AsyncClient,
    wav_bytes: bytes,
    language: str,
) -> dict[str, Any]:
    """POST multipart to whisperx-svc and return parsed JSON response.

    Raises ``httpx.HTTPStatusError`` on non-2xx responses (Prefect retries
    will handle transient 5xx / timeouts).
    """
    url = f"{_whisperx_url}/transcribe"
    files = {"audio": ("audio.wav", wav_bytes, "audio/wav")}
    data = {"language": language}

    response = await client.post(url, files=files, data=data)
    response.raise_for_status()

    result = response.json()
    if not isinstance(result, dict):
        raise DomainError(
            "invalid_state",
            f"whisperx returned non-object response: {type(result).__name__}",
        )
    return result


async def _emit_stage_failed(
    session_factory: _SessionFactory,
    *,
    episode_id: str,
    chunk_id: str,
    error: str,
) -> None:
    """Best-effort stage_failed event write — never masks the real error."""
    try:
        async with _session_scope(session_factory) as session:
            await write_event(
                session,
                episode_id=episode_id,
                chunk_id=chunk_id,
                kind="stage_failed",
                payload={"stage": "p3", "error": error},
            )
            await session.commit()
    except Exception:  # pragma: no cover
        log.exception("failed to emit stage_failed event for chunk %s", chunk_id)


# ---------------------------------------------------------------------------
# Prefect task wrapper
# ---------------------------------------------------------------------------


@task(
    name="p3-transcribe",
    retries=5,
    retry_delay_seconds=[2, 4, 8, 16, 32],
)
async def p3_transcribe(
    chunk_id: str,
    language: str = "zh",
) -> P3Result:
    """Prefect-wrapped entry point. See :func:`run_p3_transcribe`."""
    return await run_p3_transcribe(chunk_id, language=language)


__all__ = [
    "p3_transcribe",
    "run_p3_transcribe",
    "configure_p3_dependencies",
]
