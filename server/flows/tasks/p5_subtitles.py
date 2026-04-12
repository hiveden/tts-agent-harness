"""P5 — subtitle assignment, Prefect task.

Per-chunk task that runs immediately after P3 transcription. Reads the
WhisperX transcript JSON from MinIO, projects the chunk's display text
onto the take's total duration using a char-weighted scheme (see
:mod:`server.core.p5_logic`), and writes an SRT file back to MinIO.

Lifecycle
---------
1. Load chunk + its selected take from DB. Validate preconditions.
2. Write a ``stage_started`` event (fires pg_notify → SSE).
3. Download ``transcript.json`` from MinIO.
4. Parse / validate via :class:`WhisperXTranscript`.
5. Pick the subtitle source text (``chunk.subtitle_text`` or ``chunk.text``).
6. Call :func:`compose_srt` to produce the SRT document deterministically.
7. Upload to MinIO under ``chunk_subtitle_key``.
8. In a single transaction: flip ``chunk.status`` → ``p5_done`` and write
   a ``stage_finished`` event.
9. Return :class:`P5Result`.

Failure modes
-------------
- Chunk missing                       → ``DomainError("not_found")``
- Chunk missing ``selected_take_id``  → ``DomainError("invalid_state")``
- Take missing duration               → ``DomainError("invalid_state")``
- Transcript object missing on MinIO  → ``DomainError("not_found")``
- Empty / unparseable transcript      → ``DomainError("invalid_state")``
- Source text is all control markers  → ``DomainError("invalid_input")``

On any failure after ``stage_started`` the task best-effort writes a
``stage_failed`` event and re-raises so Prefect's retry policy kicks in.
P5 is a pure transform so ``retries=2`` is plenty — failures are either
deterministic bugs or transient I/O.
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable

from prefect import task
from sqlalchemy.ext.asyncio import AsyncSession

from server.core.domain import (
    DomainError,
    P5Result,
    WhisperXTranscript,
)
from server.core.events import write_event
from server.core.p5_logic import compose_srt
from server.core.repositories import ChunkRepo, TakeRepo
from server.core.storage import (
    MinIOStorage,
    chunk_subtitle_key,
    chunk_transcript_key,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Dependency wiring (mirrors server.flows.tasks.p2_synth)
# ---------------------------------------------------------------------------

_SessionFactory = Callable[[], Any]  # returns an async ctx manager → AsyncSession

_session_factory: _SessionFactory | None = None
_storage: MinIOStorage | None = None


def configure_p5_dependencies(
    *,
    session_factory: _SessionFactory,
    storage: MinIOStorage,
) -> None:
    """Inject process-wide dependencies for the p5_subtitles task.

    Called once at worker startup (real runtime) or from test fixtures.
    """
    global _session_factory, _storage
    _session_factory = session_factory
    _storage = storage


def _require_deps() -> tuple[_SessionFactory, MinIOStorage]:
    if _session_factory is None or _storage is None:
        raise RuntimeError(
            "p5_subtitles dependencies not configured. "
            "Call configure_p5_dependencies(...) before running the task."
        )
    return _session_factory, _storage


@asynccontextmanager
async def _session_scope(factory: _SessionFactory) -> AsyncIterator[AsyncSession]:
    ctx = factory()
    async with ctx as session:  # type: ignore[misc]
        yield session


# ---------------------------------------------------------------------------
# Core routine (testable without a Prefect runtime)
# ---------------------------------------------------------------------------


async def run_p5_subtitles(chunk_id: str) -> P5Result:
    """Pure coroutine body of the P5 task.

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
        total_duration = float(take.duration_s or 0.0)
        if total_duration <= 0:
            raise DomainError(
                "invalid_state",
                f"take {take.id} has non-positive duration {total_duration}",
            )
        episode_id = chunk.episode_id
        source_text = (chunk.subtitle_text or "").strip() or (chunk.text or "")

        # 2. stage_started event.
        started_at = datetime.now(timezone.utc)
        await write_event(
            session,
            episode_id=episode_id,
            chunk_id=chunk_id,
            kind="stage_started",
            payload={
                "stage": "p5",
                "started_at": started_at.isoformat(),
            },
        )
        await session.commit()

    # 3. Download + parse transcript (outside DB tx).
    transcript_key = chunk_transcript_key(episode_id, chunk_id)
    try:
        raw = await storage.download_bytes(transcript_key)
    except Exception as exc:  # noqa: BLE001 — any storage failure is surfaced
        await _emit_stage_failed(
            session_factory,
            episode_id=episode_id,
            chunk_id=chunk_id,
            error=f"transcript download failed: {type(exc).__name__}: {exc}",
        )
        raise DomainError(
            "not_found",
            f"transcript object missing for chunk {chunk_id}: {exc}",
        ) from exc

    if not raw:
        await _emit_stage_failed(
            session_factory,
            episode_id=episode_id,
            chunk_id=chunk_id,
            error="empty transcript payload",
        )
        raise DomainError("invalid_state", "transcript payload is empty")

    try:
        transcript_obj = json.loads(raw.decode("utf-8"))
        transcript = WhisperXTranscript.model_validate(transcript_obj)
    except Exception as exc:
        await _emit_stage_failed(
            session_factory,
            episode_id=episode_id,
            chunk_id=chunk_id,
            error=f"transcript parse failed: {exc}",
        )
        raise DomainError("invalid_state", f"transcript parse failed: {exc}") from exc

    if not transcript.transcript:
        await _emit_stage_failed(
            session_factory,
            episode_id=episode_id,
            chunk_id=chunk_id,
            error="transcript has zero words",
        )
        raise DomainError("invalid_state", "transcript has zero words")

    # 4. Compose SRT (pure). Prefer the duration carried on the take
    #    because that is what the user's audio actually sounds like; the
    #    transcript's ``duration_s`` is informational only.
    srt_doc, line_count = compose_srt(source_text, total_duration)
    if line_count == 0:
        # All-control-marker / empty text after stripping.
        await _emit_stage_failed(
            session_factory,
            episode_id=episode_id,
            chunk_id=chunk_id,
            error="source text has zero displayable characters",
        )
        raise DomainError(
            "invalid_input",
            f"chunk {chunk_id} has no displayable subtitle text",
        )

    # 5. Upload SRT.
    subtitle_key = chunk_subtitle_key(episode_id, chunk_id)
    try:
        subtitle_uri = await storage.upload_bytes(
            subtitle_key,
            srt_doc.encode("utf-8"),
            content_type="application/x-subrip",
        )
    except Exception as exc:
        await _emit_stage_failed(
            session_factory,
            episode_id=episode_id,
            chunk_id=chunk_id,
            error=f"subtitle upload failed: {exc}",
        )
        raise

    # 6. Persist state + stage_finished event.
    async with _session_scope(session_factory) as session:
        # chunk.status stays "verified" — fine-grained progress via stage_runs
        pass
        await write_event(
            session,
            episode_id=episode_id,
            chunk_id=chunk_id,
            kind="stage_finished",
            payload={
                "stage": "p5",
                "subtitle_uri": subtitle_uri,
                "line_count": line_count,
                "total_duration_s": total_duration,
            },
        )
        await session.commit()

    return P5Result(
        chunk_id=chunk_id,
        subtitle_uri=subtitle_uri,
        line_count=line_count,
    )


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
                payload={"stage": "p5", "error": error},
            )
            await session.commit()
    except Exception:  # pragma: no cover
        log.exception("failed to emit stage_failed event for chunk %s", chunk_id)


# ---------------------------------------------------------------------------
# Prefect task wrapper
# ---------------------------------------------------------------------------


@task(name="p5-subtitles", retries=2, retry_delay_seconds=[2, 8])
async def p5_subtitles(chunk_id: str) -> P5Result:
    """Prefect-wrapped entry point. See :func:`run_p5_subtitles`."""
    return await run_p5_subtitles(chunk_id)


__all__ = [
    "p5_subtitles",
    "run_p5_subtitles",
    "configure_p5_dependencies",
]
