"""run-episode — main Prefect flow orchestrating the TTS pipeline.

Supports multiple run modes (D-03 product design):
- "chunk_only": Only P1 (split script into chunks)
- "synthesize": P2→P3→P5→P6, skipping chunks with selected_take (D-05)
- "retry_failed": Only re-run failed chunks from their failed stage
- "regenerate": Clear all, re-run P1→P2→P3→P5→P6

Status transitions:
  episode: empty → ready (P1) → running → done (P6)
  chunk: pending → synth_done (P2) → transcribed (P3)
"""

from __future__ import annotations

import logging
from typing import Any

from prefect import flow

from server.core.domain import P1Result, P6Result
from server.flows.tasks.p1_chunk import P1Context, p1_chunk
from server.flows.tasks.p2_synth import p2_synth
from server.flows.tasks.p3_transcribe import p3_transcribe
from server.flows.tasks.p5_subtitles import p5_subtitles
from server.flows.tasks.p6_concat import p6_concat

log = logging.getLogger(__name__)


@flow(name="run-episode")
async def run_episode_flow(
    episode_id: str,
    *,
    mode: str = "synthesize",
    chunk_ids: list[str] | None = None,
    language: str = "zh",
    padding_ms: int = 200,
    shot_gap_ms: int = 500,
) -> dict[str, Any]:
    """Orchestrate the TTS pipeline for one episode.

    Parameters
    ----------
    episode_id : str
    mode : str
        "chunk_only" | "synthesize" | "retry_failed" | "regenerate"
    chunk_ids : list[str] | None
        If provided, only process these chunks (multi-select). None = all.
    language : str
        Language code for WhisperX.
    padding_ms / shot_gap_ms : int
        P6 concat parameters.
    """
    log.info("run-episode [%s] mode=%s ep=%s", mode, mode, episode_id)

    if mode == "chunk_only":
        return await _run_chunk_only(episode_id)
    elif mode == "synthesize":
        return await _run_synthesize(episode_id, chunk_ids, language, padding_ms, shot_gap_ms)
    elif mode == "retry_failed":
        return await _run_retry_failed(episode_id, language, padding_ms, shot_gap_ms)
    elif mode == "regenerate":
        return await _run_regenerate(episode_id, language, padding_ms, shot_gap_ms)
    else:
        raise ValueError(f"unknown mode: {mode}")


async def _run_chunk_only(episode_id: str) -> dict[str, Any]:
    """Mode: chunk_only — Only P1, split script into chunks."""
    from server.flows.worker_bootstrap import get_p1_context

    ctx = get_p1_context()
    p1_result: P1Result = await p1_chunk(episode_id, ctx=ctx)
    log.info("P1 complete: %d chunks", len(p1_result.chunks))
    return {"mode": "chunk_only", "chunk_count": len(p1_result.chunks)}


async def _run_synthesize(
    episode_id: str,
    chunk_ids: list[str] | None,
    language: str,
    padding_ms: int,
    shot_gap_ms: int,
) -> dict[str, Any]:
    """Mode: synthesize — P2→P3→P5→P6, skipping chunks with selected_take (D-05)."""
    from server.flows.worker_bootstrap import bootstrap, _session_factory

    if _session_factory is None:
        bootstrap()

    from server.core.repositories import ChunkRepo, EpisodeRepo
    async with _session_factory() as session:  # type: ignore[misc]
        chunk_repo = ChunkRepo(session)
        ep_repo = EpisodeRepo(session)
        all_chunks = await chunk_repo.list_by_episode(episode_id)
        ep = await ep_repo.get(episode_id)
        tts_config = (ep.config if ep else None) or {}

    # Filter to requested chunk_ids if provided
    if chunk_ids is not None:
        target_chunks = [c for c in all_chunks if c.id in set(chunk_ids)]
    else:
        target_chunks = list(all_chunks)

    # D-05: Skip P2 for chunks that already have a selected_take
    need_p2 = [c.id for c in target_chunks if c.selected_take_id is None]
    skip_p2 = [c.id for c in target_chunks if c.selected_take_id is not None]
    all_ids = [c.id for c in target_chunks]

    if skip_p2:
        log.info("D-05: skipping P2 for %d chunks (have selected_take)", len(skip_p2))

    # P2: only for chunks without take; pass episode.config as TTS params
    if need_p2:
        p2_params = tts_config if tts_config else None
        p2_futures = p2_synth.map(need_p2, [p2_params] * len(need_p2))
        [await f.result() for f in p2_futures]
        log.info("P2 complete: %d synthesized, %d skipped, config=%s", len(need_p2), len(skip_p2), bool(tts_config))
    else:
        log.info("P2 skipped entirely (all chunks have takes)")

    # P3: transcribe all target chunks (even if P2 was skipped — transcript may need refresh)
    p3_futures = p3_transcribe.map(all_ids, [language] * len(all_ids))
    [await f.result() for f in p3_futures]
    log.info("P3 complete: %d transcripts", len(all_ids))

    # P5: subtitles for all target chunks
    p5_futures = p5_subtitles.map(all_ids)
    [await f.result() for f in p5_futures]
    log.info("P5 complete: %d subtitles", len(all_ids))

    # P6: concat (always runs on full episode, not just targets)
    p6_result: P6Result = await p6_concat(episode_id, padding_ms=padding_ms, shot_gap_ms=shot_gap_ms)
    log.info("P6 complete: %s", p6_result.wav_uri)

    return {
        "mode": "synthesize",
        "synthesized": len(need_p2),
        "skipped_p2": len(skip_p2),
        "total": len(all_ids),
    }


async def _run_retry_failed(
    episode_id: str,
    language: str,
    padding_ms: int,
    shot_gap_ms: int,
) -> dict[str, Any]:
    """Mode: retry_failed — Only re-run chunks with status='failed'."""
    from server.flows.worker_bootstrap import bootstrap, _session_factory

    if _session_factory is None:
        bootstrap()

    from server.core.repositories import ChunkRepo, EpisodeRepo
    async with _session_factory() as session:  # type: ignore[misc]
        chunk_repo = ChunkRepo(session)
        all_chunks = await chunk_repo.list_by_episode(episode_id)
        ep_repo = EpisodeRepo(session)
        ep = await ep_repo.get(episode_id)
        tts_config = (ep.config if ep else None) or {}

    failed = [c for c in all_chunks if c.status == "failed"]
    if not failed:
        log.info("No failed chunks to retry")
        return {"mode": "retry_failed", "retried": 0}

    failed_ids = [c.id for c in failed]
    log.info("Retrying %d failed chunks", len(failed_ids))

    # Re-run P2→P3→P5 for failed chunks, using episode.config
    p2_params = tts_config if tts_config else None
    p2_futures = p2_synth.map(failed_ids, [p2_params] * len(failed_ids))
    [await f.result() for f in p2_futures]

    p3_futures = p3_transcribe.map(failed_ids, [language] * len(failed_ids))
    [await f.result() for f in p3_futures]

    p5_futures = p5_subtitles.map(failed_ids)
    [await f.result() for f in p5_futures]

    # P6: re-concat full episode
    p6_result = await p6_concat(episode_id, padding_ms=padding_ms, shot_gap_ms=shot_gap_ms)
    log.info("P6 complete after retry: %s", p6_result.wav_uri)

    return {"mode": "retry_failed", "retried": len(failed_ids)}


async def _run_regenerate(
    episode_id: str,
    language: str,
    padding_ms: int,
    shot_gap_ms: int,
) -> dict[str, Any]:
    """Mode: regenerate — Clear everything, re-run P1→P2→P3→P5→P6."""
    from server.flows.worker_bootstrap import get_p1_context, bootstrap, _session_factory

    if _session_factory is None:
        bootstrap()

    # Read episode config for P2 params
    from server.core.repositories import EpisodeRepo
    async with _session_factory() as session:  # type: ignore[misc]
        ep_repo = EpisodeRepo(session)
        ep = await ep_repo.get(episode_id)
        tts_config = (ep.config if ep else None) or {}

    # P1 clears chunks (DELETE + bulk_insert)
    ctx = get_p1_context()
    p1_result = await p1_chunk(episode_id, ctx=ctx)
    chunk_ids = [c.id for c in p1_result.chunks]
    log.info("P1 regenerated: %d chunks", len(chunk_ids))

    p2_params = tts_config if tts_config else None
    p2_futures = p2_synth.map(chunk_ids, [p2_params] * len(chunk_ids))
    [await f.result() for f in p2_futures]

    p3_futures = p3_transcribe.map(chunk_ids, [language] * len(chunk_ids))
    [await f.result() for f in p3_futures]

    p5_futures = p5_subtitles.map(chunk_ids)
    [await f.result() for f in p5_futures]

    p6_result = await p6_concat(episode_id, padding_ms=padding_ms, shot_gap_ms=shot_gap_ms)

    return {
        "mode": "regenerate",
        "chunk_count": len(chunk_ids),
        "wav_uri": p6_result.wav_uri,
    }


__all__ = ["run_episode_flow"]
