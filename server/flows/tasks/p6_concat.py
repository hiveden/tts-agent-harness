"""P6 — per-episode ffmpeg concat Prefect task.

Responsibilities (see A7-P6 brief and ADR-002 §4.4):

1. Load every chunk of the episode from the business DB.
2. Verify all chunks have a ``selected_take_id`` (otherwise the episode is
   not ready for finalization — raise ``DomainError('invalid_state')``).
3. Order chunks by ``(shot_id, idx)``, download each take WAV and each
   chunk SRT from MinIO into a scratch directory.
4. Generate the two silence segments (``padding_ms`` / ``shot_gap_ms``)
   exactly once, then build an ffmpeg concat list that weaves the chunk
   WAVs and the right silence between each pair.
5. Run ``ffmpeg -f concat -safe 0 -c copy`` to produce ``episode.wav``.
6. Shift and merge the per-chunk SRTs into ``episode.srt``.
7. Upload both finals to MinIO under the ``final_*_key`` paths, overwriting
   any prior run (P6 is idempotent by design).
8. Write ``stage_started`` + ``stage_finished`` events and flip the episode
   status to ``done``.

Everything that can be unit-tested without ffmpeg lives in
``server.core.p6_logic``. This module is the glue between that and the
Prefect / DB / MinIO world.
"""

from __future__ import annotations

import logging
import os
import tempfile
from contextlib import asynccontextmanager  # kept for potential future use
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator

from prefect import task
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from server.core import events as events_module
from server.core.domain import DomainError, P6Result
from server.core.p6_logic import (
    ChunkTiming,
    build_ffmpeg_concat_list,
    compute_chunk_offsets,
    compute_gap_sequence,
    compute_total_duration,
    generate_silence,
    interleave_with_silences,
    merge_srt_files,
    run_ffmpeg_concat,
    sort_chunk_timings,
)
from server.core.repositories import ChunkRepo, EpisodeRepo, TakeRepo
from server.core.storage import (
    MinIOStorage,
    chunk_subtitle_key,
    chunk_take_key,
    final_srt_key,
    final_wav_key,
)

log = logging.getLogger(__name__)


async def _emit_stage_failed(
    session_factory: async_sessionmaker,
    *,
    episode_id: str,
    error: str,
) -> None:
    """Best-effort stage_failed event write — never masks the real error."""
    try:
        async with session_factory() as session:
            await events_module.write_event(
                session,
                episode_id=episode_id,
                chunk_id=None,
                kind="stage_failed",
                payload={"stage": "p6", "error": error},
            )
            await session.commit()
    except Exception:  # pragma: no cover
        log.exception("failed to emit stage_failed event for episode %s", episode_id)


# ---------------------------------------------------------------------------
# Environment plumbing (kept tiny — A8-Flow will pass real deps later)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Module-level DI (consistent with P2/P3/P5 pattern).
# Call ``configure_p6_dependencies(...)`` once at worker startup.
# ---------------------------------------------------------------------------

_SESSION_FACTORY: async_sessionmaker | None = None
_STORAGE: MinIOStorage | None = None


def configure_p6_dependencies(
    *,
    session_factory: async_sessionmaker,
    storage: MinIOStorage,
) -> None:
    """Inject shared DB + MinIO handles. Called once by worker_bootstrap."""
    global _SESSION_FACTORY, _STORAGE
    _SESSION_FACTORY = session_factory
    _STORAGE = storage


def _get_session_factory() -> async_sessionmaker:
    if _SESSION_FACTORY is not None:
        return _SESSION_FACTORY
    # Fallback: create from env (keeps standalone dev mode working)
    from server.core.db import _database_url
    url = _database_url()
    return async_sessionmaker(create_async_engine(url, future=True), expire_on_commit=False)


def _get_storage() -> MinIOStorage:
    if _STORAGE is not None:
        return _STORAGE
    # Fallback: create from env
    return MinIOStorage(
        endpoint=os.getenv("MINIO_ENDPOINT", "localhost:59000"),
        access_key=os.getenv("MINIO_ACCESS_KEY", "minioadmin"),
        secret_key=os.getenv("MINIO_SECRET_KEY", "minioadmin"),
        bucket=os.getenv("MINIO_BUCKET", "tts-harness"),
        secure=os.getenv("MINIO_SECURE", "false").lower() == "true",
    )


# ---------------------------------------------------------------------------
# Core implementation (callable from tests without Prefect runtime)
# ---------------------------------------------------------------------------


async def run_p6_concat(
    episode_id: str,
    *,
    padding_ms: int = 200,
    shot_gap_ms: int = 500,
    session: AsyncSession,
    storage: MinIOStorage,
    workdir: Path | None = None,
) -> P6Result:
    """Execute the P6 concat for a single episode.

    The caller owns the ``session`` transaction lifecycle — this function
    calls ``flush``/``commit`` on it so both the events and the episode
    status transition are visible to downstream listeners.
    """
    padding_s = padding_ms / 1000.0
    shot_gap_s = shot_gap_ms / 1000.0

    log.info(
        "P6 start episode=%s padding_ms=%d shot_gap_ms=%d",
        episode_id,
        padding_ms,
        shot_gap_ms,
    )

    ep_repo = EpisodeRepo(session)
    chunk_repo = ChunkRepo(session)
    take_repo = TakeRepo(session)

    # Resolve the session_factory for best-effort error events.
    # We need this before any validation so pre-check errors can emit too.
    _sf = _get_session_factory()

    episode = await ep_repo.get(episode_id)
    if episode is None:
        await _emit_stage_failed(_sf, episode_id=episode_id, error=f"episode not found: {episode_id}")
        raise DomainError("not_found", f"episode not found: {episode_id}")

    chunks = list(await chunk_repo.list_by_episode(episode_id))
    if not chunks:
        await _emit_stage_failed(_sf, episode_id=episode_id, error=f"episode has no chunks: {episode_id}")
        raise DomainError("invalid_state", f"episode has no chunks: {episode_id}")

    missing = [c.id for c in chunks if not c.selected_take_id]
    if missing:
        msg = f"chunks missing selected_take_id: {missing}"
        await _emit_stage_failed(_sf, episode_id=episode_id, error=msg)
        raise DomainError(
            "invalid_state",
            msg,
        )

    # Fetch takes + build timing list.
    timings: list[ChunkTiming] = []
    take_ids: dict[str, str] = {}  # chunk_id -> take_id
    for c in chunks:
        take = await take_repo.select(c.selected_take_id)  # type: ignore[arg-type]
        if take is None:
            msg = f"take not found for chunk {c.id}: {c.selected_take_id}"
            await _emit_stage_failed(_sf, episode_id=episode_id, error=msg)
            raise DomainError(
                "not_found",
                msg,
            )
        take_ids[c.id] = take.id
        timings.append(
            ChunkTiming(
                chunk_id=c.id,
                shot_id=c.shot_id,
                idx=c.idx,
                duration_s=float(take.duration_s or 0.0),
            )
        )

    timings = sort_chunk_timings(timings)

    # Drop zero-duration chunks (log warning) — per the A7-P6 brief edge case.
    zero = [t.chunk_id for t in timings if t.duration_s <= 0]
    if zero:
        log.warning(
            "p6_concat: skipping %d zero-duration chunk(s): %s",
            len(zero),
            zero,
        )
        timings = [t for t in timings if t.duration_s > 0]

    if not timings:
        msg = f"episode has no non-empty chunks: {episode_id}"
        await _emit_stage_failed(_sf, episode_id=episode_id, error=msg)
        raise DomainError(
            "invalid_state",
            msg,
        )

    # ------------------------------------------------------------------
    # stage_started event (commit so SSE listeners see it before ffmpeg)
    # ------------------------------------------------------------------
    await events_module.write_event(
        session,
        episode_id=episode_id,
        chunk_id=None,
        kind="stage_started",
        payload={
            "stage": "p6",
            "chunk_count": len(timings),
            "padding_ms": padding_ms,
            "shot_gap_ms": shot_gap_ms,
            "started_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    await session.commit()

    # ------------------------------------------------------------------
    # Download + ffmpeg concat inside a temp workdir
    # ------------------------------------------------------------------
    offsets = compute_chunk_offsets(timings, padding_s, shot_gap_s)
    gaps = compute_gap_sequence(timings, padding_s, shot_gap_s)
    total_duration = compute_total_duration(timings, padding_s, shot_gap_s)

    log.info(
        "P6 timings_ready episode=%s chunks=%d total_duration=%.2f",
        episode_id,
        len(timings),
        total_duration,
    )

    cleanup_tmp = workdir is None
    work_root = Path(workdir or tempfile.mkdtemp(prefix=f"p6-{episode_id}-"))
    work_root.mkdir(parents=True, exist_ok=True)

    try:
        audio_paths: list[Path] = []
        srt_strings: list[str] = []

        for timing in timings:
            take_id = take_ids[timing.chunk_id]
            wav_key = chunk_take_key(episode_id, timing.chunk_id, take_id)
            if not await storage.exists(wav_key):
                raise DomainError(
                    "not_found",
                    f"take wav not in object store: {wav_key}",
                )
            wav_bytes = await storage.download_bytes(wav_key)
            wav_path = work_root / f"{timing.chunk_id}.wav"
            wav_path.write_bytes(wav_bytes)
            audio_paths.append(wav_path)

            srt_key = chunk_subtitle_key(episode_id, timing.chunk_id)
            if await storage.exists(srt_key):
                srt_bytes = await storage.download_bytes(srt_key)
                srt_strings.append(srt_bytes.decode("utf-8", errors="replace"))
            else:
                # No subtitle for this chunk → contribute empty SRT.
                srt_strings.append("")

        # Generate unique silence segments.
        silence_files: dict[float, Path] = {}
        for gap in set(gaps):
            if gap <= 0:
                continue
            sil_path = work_root / f"silence_{int(round(gap * 1000))}.wav"
            await generate_silence(sil_path, gap)
            silence_files[gap] = sil_path

        interleaved = interleave_with_silences(audio_paths, gaps, silence_files)
        concat_body = build_ffmpeg_concat_list(interleaved)
        list_file = work_root / "concat.txt"
        list_file.write_text(concat_body, encoding="utf-8")

        wav_out = work_root / "episode.wav"
        await run_ffmpeg_concat(list_file, wav_out)

        # Merge SRTs in pure-Python.
        merged_srt = merge_srt_files(srt_strings, offsets)
        srt_out = work_root / "episode.srt"
        srt_out.write_text(merged_srt, encoding="utf-8")

        # Upload finals (overwrite on re-run — MinIO put_object replaces).
        wav_uri = await storage.upload_file(final_wav_key(episode_id), wav_out)
        srt_uri = await storage.upload_file(final_srt_key(episode_id), srt_out)

        log.info(
            "P6 uploaded episode=%s wav=%s srt=%s total_duration=%.2f",
            episode_id,
            wav_uri,
            srt_uri,
            total_duration,
        )
    except Exception as exc:
        await _emit_stage_failed(_sf, episode_id=episode_id, error=str(exc))
        raise
    finally:
        if cleanup_tmp:
            try:
                for p in sorted(work_root.glob("**/*"), reverse=True):
                    if p.is_file():
                        p.unlink(missing_ok=True)
                    else:
                        p.rmdir()
                work_root.rmdir()
            except OSError:
                log.warning("p6_concat: failed to clean workdir %s", work_root)

    result = P6Result(
        episode_id=episode_id,
        wav_uri=wav_uri,
        srt_uri=srt_uri,
        total_duration_s=total_duration,
        chunk_count=len(timings),
    )

    # ------------------------------------------------------------------
    # stage_finished + episode.status → done
    # ------------------------------------------------------------------
    await events_module.write_event(
        session,
        episode_id=episode_id,
        chunk_id=None,
        kind="stage_finished",
        payload={
            "stage": "p6",
            "wav_uri": wav_uri,
            "srt_uri": srt_uri,
            "total_duration_s": total_duration,
            "chunk_count": len(timings),
            "finished_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    await ep_repo.set_status(episode_id, "done")
    await session.commit()

    log.info(
        "P6 done episode=%s chunks=%d total_duration=%.2f",
        episode_id,
        len(timings),
        total_duration,
    )

    return result


# ---------------------------------------------------------------------------
# Prefect wrapper (thin — owns DB + storage lifecycle only)
# ---------------------------------------------------------------------------


@task(name="p6-concat", retries=2)
async def p6_concat(
    episode_id: str,
    padding_ms: int = 200,
    shot_gap_ms: int = 500,
) -> P6Result:
    """Prefect entry point. Owns DB session + MinIO client lifecycle."""
    storage = _get_storage()
    factory = _get_session_factory()
    async with factory() as session:
        return await run_p6_concat(
            episode_id,
            padding_ms=padding_ms,
            shot_gap_ms=shot_gap_ms,
            session=session,
            storage=storage,
        )


__all__ = ["p6_concat", "run_p6_concat"]
