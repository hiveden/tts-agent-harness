"""P2 — Fish Audio TTS synthesis, Prefect task.

Per ADR-001 §4.3 this task carries the ``fish-api`` concurrency tag so that
a Prefect global concurrency limit governs all synthesis traffic, no
matter how many worker replicas are running. Retry/backoff is also
delegated to Prefect (``retries=3`` + explicit ``retry_delay_seconds``
list) — we do **not** sleep / backoff by hand.

Per-call lifecycle
------------------
1. Load chunk + episode from DB. Validate preconditions.
2. Write a ``stage_started`` event (fires pg_notify → SSE).
3. Call :class:`FishTTSClient.synthesize` to get WAV bytes.
4. Compute WAV duration (wave module, pure stdlib).
5. Upload bytes to MinIO under the canonical ``chunk_take_key``.
6. In a single transaction:

   - ``takes`` INSERT (new take row)
   - ``chunks.selected_take_id`` = new take id
   - ``chunks.status`` = ``synth_done``
   - ``stage_finished`` event

7. Return :class:`P2Result`.

Failure paths
-------------
- Chunk missing → ``DomainError("not_found")``, fatal.
- Empty text_normalized → ``DomainError("invalid_input")``, fatal.
- Fish auth error → :class:`FishAuthError`, fatal (Prefect sees fatal
  but still retries; we rely on ADR §4.3 saying "credential issues are
  escalated out-of-band" — at the flow layer A8 can map the exception to
  a non-retryable state if needed).
- Fish 429 / 5xx / network → let Prefect retry via ``retries=3``.
- MinIO upload failure → raise, no take row written.

On any failure after ``stage_started`` the task writes a ``stage_failed``
event so the SSE stream stays informative. The task then re-raises the
original exception so Prefect can decide whether to retry.
"""

from __future__ import annotations

import io
import logging
import os
import wave
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Awaitable, Callable

from prefect import task
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from server.core.domain import DomainError, FishTTSParams, P2Result, TakeAppend
from server.core.events import write_event
from server.core.fish_client import (
    FishAuthError,
    FishClientError,
    FishTTSClient,
    build_params_from_env,
)
from server.core.repositories import ChunkRepo, TakeRepo
from server.core.storage import MinIOStorage, chunk_take_key

log = logging.getLogger(__name__)

# Text longer than this triggers a non-fatal warning (Fish may truncate).
TEXT_LENGTH_WARN_THRESHOLD = 3000


# ---------------------------------------------------------------------------
# Dependency wiring
# ---------------------------------------------------------------------------


# Tests inject these at module level via ``configure_p2_dependencies`` so that
# the @task decorated function can be called without a full DI container.
_SessionFactory = Callable[[], "AsyncSessionCtxManager"]
AsyncSessionCtxManager = Any  # async context manager yielding AsyncSession

_session_factory: _SessionFactory | None = None
_storage: MinIOStorage | None = None
_fish_client_factory: Callable[[], FishTTSClient] | None = None


def configure_p2_dependencies(
    *,
    session_factory: _SessionFactory,
    storage: MinIOStorage,
    fish_client_factory: Callable[[], FishTTSClient],
) -> None:
    """Inject process-wide dependencies for the p2_synth task.

    The Prefect worker startup hook calls this once; tests call it in a
    fixture. Keeping state at module level avoids having to thread
    ``FastAPI.state``-style containers through Prefect's task signature.
    """
    global _session_factory, _storage, _fish_client_factory
    _session_factory = session_factory
    _storage = storage
    _fish_client_factory = fish_client_factory


def _require_deps() -> tuple[_SessionFactory, MinIOStorage, Callable[[], FishTTSClient]]:
    if _session_factory is None or _storage is None or _fish_client_factory is None:
        raise RuntimeError(
            "p2_synth dependencies not configured. "
            "Call configure_p2_dependencies(...) before running the task."
        )
    return _session_factory, _storage, _fish_client_factory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _new_take_id() -> str:
    """Generate a globally-unique take id (ulid → lexicographically sortable)."""
    try:
        import ulid

        return str(ulid.ULID())
    except Exception:  # pragma: no cover - ulid is a hard dep
        import uuid

        return f"tk_{uuid.uuid4().hex}"


def _wav_duration_seconds(data: bytes) -> float:
    """Best-effort WAV duration via stdlib ``wave`` module.

    Fish TTS streaming WAV may have incorrect nframes in the header
    (e.g. 2^31 - 128), so we compute duration from actual data size
    instead of trusting getnframes().
    """
    try:
        with wave.open(io.BytesIO(data), "rb") as wf:
            rate = wf.getframerate()
            channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            if rate <= 0 or channels <= 0 or sampwidth <= 0:
                return 0.0
            # Calculate from actual data size, not nframes (which may be wrong)
            header_size = 44  # standard WAV header
            audio_bytes = max(0, len(data) - header_size)
            bytes_per_sample = channels * sampwidth
            return audio_bytes / (rate * bytes_per_sample)
    except wave.Error:
        return 0.0
    except Exception:
        return 0.0


@asynccontextmanager
async def _session_scope(factory: _SessionFactory) -> AsyncIterator[AsyncSession]:
    """Yield an ``AsyncSession`` from the injected factory.

    Supports both a plain ``async_sessionmaker`` (async context manager on
    call) and arbitrary callables returning an async ctx manager.
    """
    ctx = factory()
    async with ctx as session:  # type: ignore[misc]
        yield session


# ---------------------------------------------------------------------------
# Core routine (testable without Prefect runtime)
# ---------------------------------------------------------------------------


async def run_p2_synth(
    chunk_id: str,
    params: FishTTSParams | dict[str, Any] | None = None,
) -> P2Result:
    """Pure coroutine that executes the P2 pipeline step.

    The ``@task`` wrapper below simply forwards to this. Keeping the body
    as a plain coroutine means unit tests do not need a Prefect runtime.
    """
    session_factory, storage, fish_factory = _require_deps()

    # Normalise params input.
    if params is None:
        fish_params = build_params_from_env()
    elif isinstance(params, FishTTSParams):
        fish_params = params
    else:
        merged = build_params_from_env().model_dump()
        merged.update(params)
        fish_params = FishTTSParams(**merged)

    # 1. Load chunk + validate.
    async with _session_scope(session_factory) as session:
        chunk = await ChunkRepo(session).get(chunk_id)
        if chunk is None:
            raise DomainError("not_found", f"chunk not found: {chunk_id}")
        text = (chunk.text_normalized or "").strip()
        if not text:
            raise DomainError(
                "invalid_input", f"chunk {chunk_id} has empty text_normalized"
            )
        episode_id = chunk.episode_id

        if len(text) > TEXT_LENGTH_WARN_THRESHOLD:
            log.warning(
                "chunk %s text_normalized length=%d exceeds %d; Fish may truncate",
                chunk_id,
                len(text),
                TEXT_LENGTH_WARN_THRESHOLD,
            )

        # 2. stage_started event.
        started_at = datetime.now(timezone.utc)
        await write_event(
            session,
            episode_id=episode_id,
            chunk_id=chunk_id,
            kind="stage_started",
            payload={
                "stage": "p2",
                "started_at": started_at.isoformat(),
            },
        )
        await session.commit()

    # 3. Fish call — outside DB transaction, runs under the fish-api
    #    concurrency limit via the Prefect task tag.
    fish_client = fish_factory()
    try:
        wav_bytes = await fish_client.synthesize(text, fish_params)
    except Exception as exc:  # noqa: BLE001 - classify downstream
        await _emit_stage_failed(
            session_factory,
            episode_id=episode_id,
            chunk_id=chunk_id,
            error=f"{type(exc).__name__}: {exc}",
        )
        raise
    finally:
        # If we own the client, close it; otherwise the caller owns it.
        try:
            await fish_client.aclose()
        except Exception:  # pragma: no cover
            pass

    if not wav_bytes:
        await _emit_stage_failed(
            session_factory,
            episode_id=episode_id,
            chunk_id=chunk_id,
            error="fish returned empty bytes",
        )
        raise FishClientError("Fish returned zero-length audio")

    duration_s = _wav_duration_seconds(wav_bytes)

    # 4. Upload to MinIO.
    take_id = _new_take_id()
    key = chunk_take_key(episode_id, chunk_id, take_id)
    try:
        audio_uri = await storage.upload_bytes(key, wav_bytes, content_type="audio/wav")
    except Exception as exc:
        await _emit_stage_failed(
            session_factory,
            episode_id=episode_id,
            chunk_id=chunk_id,
            error=f"minio upload failed: {exc}",
        )
        raise

    # 5. Persist take + flip chunk state + stage_finished event.
    async with _session_scope(session_factory) as session:
        take = await TakeRepo(session).append(
            TakeAppend(
                id=take_id,
                chunk_id=chunk_id,
                audio_uri=audio_uri,
                duration_s=duration_s,
                params=fish_params.model_dump(),
            )
        )
        chunk_repo = ChunkRepo(session)
        await chunk_repo.set_selected_take(chunk_id, take.id)
        await chunk_repo.set_status(chunk_id, "synth_done")
        await write_event(
            session,
            episode_id=episode_id,
            chunk_id=chunk_id,
            kind="stage_finished",
            payload={
                "stage": "p2",
                "take_id": take.id,
                "audio_uri": audio_uri,
                "duration_s": duration_s,
            },
        )
        await write_event(
            session,
            episode_id=episode_id,
            chunk_id=chunk_id,
            kind="take_appended",
            payload={"take_id": take.id, "audio_uri": audio_uri},
        )
        await session.commit()

    return P2Result(
        chunk_id=chunk_id,
        take_id=take_id,
        audio_uri=audio_uri,
        duration_s=duration_s,
        params=fish_params.model_dump(),
    )


async def _emit_stage_failed(
    session_factory: _SessionFactory,
    *,
    episode_id: str,
    chunk_id: str,
    error: str,
) -> None:
    """Best-effort stage_failed event write.

    Failure to emit the event must never mask the underlying task failure
    — Prefect still sees the original exception and applies its retry
    policy.
    """
    try:
        async with _session_scope(session_factory) as session:
            await write_event(
                session,
                episode_id=episode_id,
                chunk_id=chunk_id,
                kind="stage_failed",
                payload={"stage": "p2", "error": error},
            )
            await session.commit()
    except Exception:  # pragma: no cover
        log.exception("failed to emit stage_failed event for chunk %s", chunk_id)


# ---------------------------------------------------------------------------
# Prefect task wrapper
# ---------------------------------------------------------------------------


@task(
    name="p2-synth",
    tags=["fish-api"],
    retries=3,
    retry_delay_seconds=[2, 8, 32],
)
async def p2_synth(
    chunk_id: str,
    params: dict[str, Any] | None = None,
) -> P2Result:
    """Prefect-wrapped entry point. See :func:`run_p2_synth` for the body.

    The concurrency limit is enforced globally via
    ``prefect concurrency-limit create fish-api <N>`` (ADR-001 §4.3) —
    worker startup must register this limit before any flow runs.
    """
    return await run_p2_synth(chunk_id, params)


__all__ = [
    "p2_synth",
    "run_p2_synth",
    "configure_p2_dependencies",
    "TEXT_LENGTH_WARN_THRESHOLD",
]
