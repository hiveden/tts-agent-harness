"""P2v — ASR transcription + quality verification, Prefect task.

Merges the former P3 (WhisperX transcription) and check3 (quality gate)
into a single verify stage. On success the chunk transitions to ``verified``
(replacing the old ``transcribed`` status).

Per-call lifecycle
------------------
1. Load chunk + selected take from DB. Validate preconditions.
2. Write a ``verify_started`` event (fires pg_notify -> SSE).
3. Download the take WAV from MinIO.
4. POST multipart (file=WAV, language=episode language) to whisperx-svc.
5. Upload transcript JSON to MinIO under ``chunk_transcript_key``.
6. Run 2-dimensional scoring via ``p2v_scoring.evaluate()``:
   duration_ratio, silence (phonetic/char/asr disabled, always 1.0).
7. If weighted_score >= 0.7 -> pass:
   - ``chunks.status`` -> ``verified``
   - ``verify_finished`` event with scores + diagnosis
8. If weighted_score < 0.7 -> fail:
   - ``chunks.status`` stays ``synth_done`` (awaiting repair)
   - ``verify_failed`` event with scores + diagnosis

Failure paths
-------------
- Chunk missing                      -> ``DomainError("not_found")``, fatal.
- Chunk missing ``selected_take_id`` -> ``DomainError("invalid_state")``, fatal.
- Take WAV missing from MinIO        -> ``DomainError("not_found")``, fatal.
- WhisperX 5xx / timeout             -> let Prefect retry via ``retries=2``.
- MinIO upload failure               -> raise, Prefect retries.
"""

from __future__ import annotations

import json
import logging
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable

import httpx
from prefect import task
from sqlalchemy.ext.asyncio import AsyncSession

from server.core.domain import (
    DomainError,
    P2vResult,
    WhisperXTranscript,
)
from server.core.events import write_event
from server.core.p2v_scoring import (
    diagnosis_to_dict,
    evaluate,
    scores_to_dict,
)
from server.core.p5_logic import strip_control_markers
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
# Dependency wiring (same pattern as p3_transcribe)
# ---------------------------------------------------------------------------

_SessionFactory = Callable[[], Any]  # returns an async ctx manager -> AsyncSession

_session_factory: _SessionFactory | None = None
_storage: MinIOStorage | None = None
_http_client_factory: Callable[[], httpx.AsyncClient] | None = None
_whisperx_url: str = DEFAULT_WHISPERX_URL
_groq_api_key: str | None = None
_groq_proxy: str | None = None


def configure_p2v_dependencies(
    *,
    session_factory: _SessionFactory,
    storage: MinIOStorage,
    http_client_factory: Callable[[], httpx.AsyncClient] | None = None,
    whisperx_url: str = DEFAULT_WHISPERX_URL,
    groq_api_key: str | None = None,
    groq_proxy: str | None = None,
) -> None:
    """Inject process-wide dependencies for the p2v_verify task."""
    global _session_factory, _storage, _http_client_factory, _whisperx_url
    global _groq_api_key, _groq_proxy
    _session_factory = session_factory
    _storage = storage
    _http_client_factory = http_client_factory
    _whisperx_url = whisperx_url
    _groq_api_key = groq_api_key
    _groq_proxy = groq_proxy


def _require_deps() -> tuple[_SessionFactory, MinIOStorage]:
    if _session_factory is None or _storage is None:
        raise RuntimeError(
            "p2v_verify dependencies not configured. "
            "Call configure_p2v_dependencies(...) before running the task."
        )
    return _session_factory, _storage


def _get_http_client() -> httpx.AsyncClient:
    """Return an httpx client -- injected or default."""
    if _http_client_factory is not None:
        return _http_client_factory()
    return httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0))


@asynccontextmanager
async def _session_scope(factory: _SessionFactory) -> AsyncIterator[AsyncSession]:
    ctx = factory()
    async with ctx as session:  # type: ignore[misc]
        yield session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_transcribed_text(transcript_data: dict[str, Any]) -> str:
    """Join all word tokens from a WhisperX transcript into plain text."""
    words = transcript_data.get("transcript", [])
    return "".join(w.get("word", "") for w in words)


def _extract_silence_segments(
    words: list[dict[str, Any]],
    duration_s: float,
    gap_threshold: float = 0.5,
) -> list[dict[str, float]]:
    """Detect silence segments from inter-word gaps in WhisperX output."""
    segments: list[dict[str, float]] = []
    if not words:
        return segments

    # Leading silence
    first_start = words[0].get("start", 0.0)
    if first_start > gap_threshold:
        segments.append({"start": 0.0, "end": first_start, "duration": first_start})

    # Inter-word gaps
    for prev, curr in zip(words, words[1:]):
        prev_end = prev.get("end", 0.0)
        curr_start = curr.get("start", 0.0)
        gap = curr_start - prev_end
        if gap > gap_threshold:
            segments.append({"start": prev_end, "end": curr_start, "duration": gap})

    # Trailing silence
    last_end = words[-1].get("end", 0.0)
    if duration_s - last_end > gap_threshold:
        segments.append({"start": last_end, "end": duration_s, "duration": duration_s - last_end})

    return segments


# ---------------------------------------------------------------------------
# Core routine (testable without Prefect runtime)
# ---------------------------------------------------------------------------


async def run_p2v_verify(
    chunk_id: str,
    *,
    language: str = "zh",
) -> P2vResult:
    """Pure coroutine body of the P2v task."""
    session_factory, storage = _require_deps()

    # 1. Load chunk + take, validate preconditions.
    async with _session_scope(session_factory) as session:
        chunk = await ChunkRepo(session).get(chunk_id)
        if chunk is None:
            await _emit_stage_failed(
                session_factory,
                episode_id="unknown",
                chunk_id=chunk_id,
                error=f"chunk not found: {chunk_id}",
            )
            raise DomainError("not_found", f"chunk not found: {chunk_id}")
        if not chunk.selected_take_id:
            await _emit_stage_failed(
                session_factory,
                episode_id=chunk.episode_id,
                chunk_id=chunk_id,
                error=f"chunk {chunk_id} has no selected_take_id",
            )
            raise DomainError(
                "invalid_state",
                f"chunk {chunk_id} has no selected_take_id",
            )
        take = await TakeRepo(session).select(chunk.selected_take_id)
        if take is None:
            await _emit_stage_failed(
                session_factory,
                episode_id=chunk.episode_id,
                chunk_id=chunk_id,
                error=f"selected take {chunk.selected_take_id} not found for chunk {chunk_id}",
            )
            raise DomainError(
                "invalid_state",
                f"selected take {chunk.selected_take_id} not found for chunk {chunk_id}",
            )
        episode_id = chunk.episode_id
        take_id = take.id
        take_duration_s = float(take.duration_s or 0.0)
        chunk_text_raw = chunk.text or ""
        original_text = strip_control_markers(chunk_text_raw)

        # 2. verify_started event.
        started_at = datetime.now(timezone.utc)
        await write_event(
            session,
            episode_id=episode_id,
            chunk_id=chunk_id,
            kind="verify_started",
            payload={
                "stage": "p2v",
                "started_at": started_at.isoformat(),
            },
        )
        await session.commit()

    # 3. Download take WAV from MinIO.
    wav_key = chunk_take_key(episode_id, chunk_id, take_id)
    try:
        wav_bytes = await storage.download_bytes(wav_key)
    except Exception as exc:
        _err = f"take WAV download failed: {type(exc).__name__}: {exc}"
        await _emit_verify_failed(session_factory, episode_id=episode_id, chunk_id=chunk_id, error=_err)
        await _emit_stage_failed(session_factory, episode_id=episode_id, chunk_id=chunk_id, error=_err)
        raise DomainError(
            "not_found",
            f"take WAV missing for chunk {chunk_id}: {wav_key}",
        ) from exc

    if not wav_bytes:
        _err = "take WAV is zero bytes"
        await _emit_verify_failed(session_factory, episode_id=episode_id, chunk_id=chunk_id, error=_err)
        await _emit_stage_failed(session_factory, episode_id=episode_id, chunk_id=chunk_id, error=_err)
        raise DomainError("invalid_state", f"take WAV is empty for chunk {chunk_id}")

    # 4. ASR transcription: Groq Whisper (if configured) or local WhisperX.
    groq_key = _groq_api_key or os.environ.get("GROQ_API_KEY", "")
    whisperx_url = _whisperx_url or os.environ.get("WHISPERX_URL", "")
    log.info("P2v ASR config: groq_key=%s whisperx_url=%s", bool(groq_key), whisperx_url)

    if groq_key:
        # Use Groq Whisper API.
        from server.core.groq_asr_client import GroqASRClient

        groq_client = GroqASRClient(api_key=groq_key, proxy=_groq_proxy)
        try:
            transcript_data = await groq_client.transcribe(wav_bytes, language)
        except Exception as exc:
            _err = f"groq asr call failed: {type(exc).__name__}: {exc}"
            await _emit_verify_failed(session_factory, episode_id=episode_id, chunk_id=chunk_id, error=_err)
            await _emit_stage_failed(session_factory, episode_id=episode_id, chunk_id=chunk_id, error=_err)
            raise
    elif whisperx_url:
        # Use local WhisperX service.
        client = _get_http_client()
        try:
            transcript_data = await _call_whisperx(client, wav_bytes, language)
        except Exception as exc:
            _err = f"whisperx call failed: {type(exc).__name__}: {exc}"
            await _emit_verify_failed(session_factory, episode_id=episode_id, chunk_id=chunk_id, error=_err)
            await _emit_stage_failed(session_factory, episode_id=episode_id, chunk_id=chunk_id, error=_err)
            raise
        finally:
            await client.aclose()
    else:
        _err = "ASR 未配置: 需要 Groq API Key 或 WhisperX URL"
        await _emit_verify_failed(session_factory, episode_id=episode_id, chunk_id=chunk_id, error=_err)
        await _emit_stage_failed(session_factory, episode_id=episode_id, chunk_id=chunk_id, error=_err)
        raise DomainError("auth_required", _err)

    # Validate transcript structure.
    try:
        transcript = WhisperXTranscript.model_validate(transcript_data)
    except Exception as exc:
        _err = f"transcript validation failed: {exc}"
        await _emit_verify_failed(session_factory, episode_id=episode_id, chunk_id=chunk_id, error=_err)
        await _emit_stage_failed(session_factory, episode_id=episode_id, chunk_id=chunk_id, error=_err)
        raise DomainError(
            "invalid_state", f"transcript validation failed: {exc}"
        ) from exc

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
        _err = f"transcript upload failed: {exc}"
        await _emit_verify_failed(session_factory, episode_id=episode_id, chunk_id=chunk_id, error=_err)
        await _emit_stage_failed(session_factory, episode_id=episode_id, chunk_id=chunk_id, error=_err)
        raise

    # 6. Quality gate: 2-dimensional scoring via p2v_scoring.evaluate().
    transcribed_text = _extract_transcribed_text(transcript_data)
    words_raw = transcript_data.get("transcript", [])
    char_count = len(re.sub(r"\s+", "", original_text))
    silence_segments = _extract_silence_segments(words_raw, take_duration_s)

    scores, diagnosis = evaluate(
        original_text=original_text,
        transcribed_text=transcribed_text,
        words=words_raw,
        duration_s=take_duration_s,
        char_count=char_count,
        silence_segments=silence_segments,
    )

    verdict = diagnosis.verdict  # "pass" or "fail"

    if verdict == "pass":
        # PASS — verified.
        async with _session_scope(session_factory) as session:
            await ChunkRepo(session).set_status(chunk_id, "verified")
            finished_at = datetime.now(timezone.utc)
            await write_event(
                session,
                episode_id=episode_id,
                chunk_id=chunk_id,
                kind="verify_finished",
                payload={
                    "stage": "p2v",
                    "transcript_uri": transcript_uri,
                    "word_count": len(transcript.transcript),
                    "scores": scores_to_dict(scores),
                    "diagnosis": diagnosis_to_dict(diagnosis),
                    "finished_at": finished_at.isoformat(),
                },
            )
            await session.commit()

        return P2vResult(
            chunk_id=chunk_id,
            verdict="pass",
            char_ratio=scores.char_ratio,
            transcript_uri=transcript_uri,
            transcribed_text=transcribed_text,
            original_text=original_text,
        )
    else:
        # FAIL — keep synth_done, record diagnostic.
        async with _session_scope(session_factory) as session:
            failed_at = datetime.now(timezone.utc)
            await write_event(
                session,
                episode_id=episode_id,
                chunk_id=chunk_id,
                kind="verify_failed",
                payload={
                    "stage": "p2v",
                    "scores": scores_to_dict(scores),
                    "diagnosis": diagnosis_to_dict(diagnosis),
                    "original_text": original_text,
                    "transcribed_text": transcribed_text,
                    "failed_at": failed_at.isoformat(),
                },
            )
            await session.commit()

        return P2vResult(
            chunk_id=chunk_id,
            verdict="fail",
            char_ratio=scores.char_ratio,
            transcript_uri=transcript_uri,
            transcribed_text=transcribed_text,
            original_text=original_text,
        )


async def _call_whisperx(
    client: httpx.AsyncClient,
    wav_bytes: bytes,
    language: str,
) -> dict[str, Any]:
    """POST multipart to whisperx-svc and return parsed JSON response."""
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


async def _emit_verify_failed(
    session_factory: _SessionFactory,
    *,
    episode_id: str,
    chunk_id: str,
    error: str,
) -> None:
    """Best-effort verify_failed event write -- never masks the real error."""
    try:
        async with _session_scope(session_factory) as session:
            await write_event(
                session,
                episode_id=episode_id,
                chunk_id=chunk_id,
                kind="verify_failed",
                payload={"stage": "p2v", "error": error},
            )
            await session.commit()
    except Exception:  # pragma: no cover
        log.exception("failed to emit verify_failed event for chunk %s", chunk_id)


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
                payload={"stage": "p2v", "error": error},
            )
            await session.commit()
    except Exception:  # pragma: no cover
        log.exception("failed to emit stage_failed event for chunk %s", chunk_id)


# ---------------------------------------------------------------------------
# Prefect task wrapper
# ---------------------------------------------------------------------------


@task(
    name="p2v-verify",
    retries=2,
    retry_delay_seconds=[2, 8],
)
async def p2v_verify(
    chunk_id: str,
    language: str = "zh",
) -> P2vResult:
    """Prefect-wrapped entry point. See :func:`run_p2v_verify`."""
    return await run_p2v_verify(chunk_id, language=language)


__all__ = [
    "p2v_verify",
    "run_p2v_verify",
    "configure_p2v_dependencies",
]
