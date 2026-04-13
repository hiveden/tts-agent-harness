"""run-episode — main Prefect flow orchestrating the TTS pipeline.

Supports multiple run modes (D-03 product design):
- "chunk_only": Only P1 (split script into chunks)
- "synthesize": P2→P2c→P2v repair loop→P5→P6, skipping chunks with selected_take (D-05)
- "retry_failed": Only re-run failed chunks from their failed stage
- "regenerate": Clear all, re-run P1→P2→P2v→P5→P6

Status transitions:
  episode: empty → ready (P1) → running → done (P6)
  chunk: pending → synth_done (P2) → verified (P2v) | needs_review
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from prefect import flow

from server.core.domain import P1Result, P2vResult, P6Result
from server.flows.tasks.p1_chunk import P1Context, p1_chunk
from server.flows.tasks.p1c_check import p1c_check
from server.flows.tasks.p2_synth import p2_synth, run_p2_synth
from server.flows.tasks.p2c_check import p2c_check, run_p2c_check
from server.flows.tasks.p2v_verify import p2v_verify, run_p2v_verify
from server.flows.tasks.p3_transcribe import p3_transcribe  # kept for backward compat
from server.flows.tasks.p5_subtitles import p5_subtitles
from server.flows.tasks.p6_concat import p6_concat
from server.flows.tasks.p6v_check import p6v_check

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


# ---------------------------------------------------------------------------
# Per-chunk synth pipeline (P2 → P2c → P2v, single pass)
# ---------------------------------------------------------------------------


async def _synth_one_chunk(
    episode_id: str,
    chunk_id: str,
    base_params: dict,
    language: str,
    *,
    _write_event: Any | None = None,
    _set_chunk_status: Any | None = None,
) -> dict[str, Any]:
    """Run P2→P2c→P2v once for a single chunk. No auto-retry loop.

    Returns a summary dict with keys: chunk_id, verdict.
    On any failure, chunk is marked needs_review immediately.
    Network-level retries are handled by Prefect task decorators.
    """
    if _write_event is None:
        from server.flows.worker_bootstrap import _session_factory
        from server.core.events import write_event as _real_write_event

        async def _write_event(ep_id, c_id, kind, payload):
            async with _session_factory() as session:
                await _real_write_event(
                    session,
                    episode_id=ep_id,
                    chunk_id=c_id,
                    kind=kind,
                    payload=payload,
                )
                await session.commit()

    if _set_chunk_status is None:
        from server.flows.worker_bootstrap import _session_factory
        from server.core.repositories import ChunkRepo

        async def _set_chunk_status(c_id, status):
            async with _session_factory() as session:
                await ChunkRepo(session).set_status(c_id, status)
                await session.commit()

    # P2: synthesize
    try:
        await run_p2_synth(chunk_id, params=base_params)
    except Exception:
        log.exception("P2 synth failed for chunk %s", chunk_id)
        await _set_chunk_status(chunk_id, "needs_review")
        await _write_event(episode_id, chunk_id, "needs_review", {"reason": "P2 synth exception"})
        return {"chunk_id": chunk_id, "verdict": "needs_review"}

    # P2c: WAV format check
    try:
        p2c_result = await run_p2c_check(chunk_id)
    except Exception:
        log.exception("P2c check failed for chunk %s", chunk_id)
        await _set_chunk_status(chunk_id, "needs_review")
        await _write_event(episode_id, chunk_id, "needs_review", {"reason": "P2c check exception"})
        return {"chunk_id": chunk_id, "verdict": "needs_review"}

    if p2c_result.get("status") == "failed":
        log.warning("P2c failed for chunk %s: %s", chunk_id, p2c_result.get("errors"))
        await _set_chunk_status(chunk_id, "needs_review")
        await _write_event(episode_id, chunk_id, "needs_review", {"reason": "P2c format check failed"})
        return {"chunk_id": chunk_id, "verdict": "needs_review"}

    # P2v: ASR transcribe + quality verify
    try:
        p2v_result: P2vResult = await run_p2v_verify(chunk_id, language=language)
    except Exception:
        log.exception("P2v verify failed for chunk %s", chunk_id)
        await _set_chunk_status(chunk_id, "needs_review")
        await _write_event(episode_id, chunk_id, "needs_review", {"reason": "P2v verify exception"})
        return {"chunk_id": chunk_id, "verdict": "needs_review"}

    if p2v_result.verdict == "pass":
        log.info("chunk %s verified", chunk_id)
        return {"chunk_id": chunk_id, "verdict": "pass"}

    # P2v quality check failed → needs_review immediately
    await _set_chunk_status(chunk_id, "needs_review")
    await _write_event(episode_id, chunk_id, "needs_review", {"reason": "P2v quality check failed"})
    log.warning("chunk %s → needs_review (quality check failed)", chunk_id)
    return {"chunk_id": chunk_id, "verdict": "needs_review"}


async def _run_synthesize(
    episode_id: str,
    chunk_ids: list[str] | None,
    language: str,
    padding_ms: int,
    shot_gap_ms: int,
) -> dict[str, Any]:
    """Mode: synthesize — P2→P2c→P2v repair loop→P5→P6, with D-05 skip."""
    from server.flows.worker_bootstrap import bootstrap, _session_factory

    if _session_factory is None:
        bootstrap()

    from server.core.repositories import ChunkRepo, EpisodeRepo
    async with _session_factory() as session:  # type: ignore[misc]
        chunk_repo = ChunkRepo(session)
        ep_repo = EpisodeRepo(session)
        all_chunks = await chunk_repo.list_by_episode(episode_id)
        ep = await ep_repo.get(episode_id)
        ep_config = (ep.config if ep else None) or {}

    tts_config = {k: v for k, v in ep_config.items() if k != "repair"}

    # Filter to requested chunk_ids if provided
    if chunk_ids is not None:
        target_chunks = [c for c in all_chunks if c.id in set(chunk_ids)]
    else:
        target_chunks = list(all_chunks)

    # D-05: Skip P2 for chunks that already have a selected_take
    need_p2 = [c for c in target_chunks if c.selected_take_id is None]
    skip_p2 = [c for c in target_chunks if c.selected_take_id is not None]
    all_ids = [c.id for c in target_chunks]

    if skip_p2:
        log.info("D-05: skipping P2 for %d chunks (have selected_take)", len(skip_p2))

    # P1c: input validation gate (only for chunks going through P2)
    need_p2_ids = [c.id for c in need_p2]
    if need_p2_ids:
        p1c_futures = p1c_check.map(need_p2_ids)
        [await f.result() for f in p1c_futures]
        log.info("P1c complete: %d chunks validated", len(need_p2_ids))

    # Per-chunk synth — single pass P2→P2c→P2v, no auto-retry.
    if need_p2_ids:
        p2_params = tts_config if tts_config else {}
        loop_tasks = [
            _synth_one_chunk(
                episode_id=episode_id,
                chunk_id=cid,
                base_params=p2_params,
                language=language,
            )
            for cid in need_p2_ids
        ]
        loop_results = await asyncio.gather(*loop_tasks)
        verified_count = sum(1 for r in loop_results if r["verdict"] == "pass")
        needs_review_count = sum(1 for r in loop_results if r["verdict"] == "needs_review")
        log.info(
            "Synth loop complete: %d verified, %d needs_review, %d skipped",
            verified_count, needs_review_count, len(skip_p2),
        )
    else:
        log.info("P2 skipped entirely (all chunks have takes)")
        loop_results = []
        verified_count = 0
        needs_review_count = 0

    # For chunks that were skipped (already had takes), also run P2v if not
    # yet verified (they may have been synthesized in a prior run).
    skip_ids = [c.id for c in skip_p2]
    if skip_ids:
        # Re-read chunk statuses to see which skipped chunks need P2v.
        async with _session_factory() as session:
            chunk_repo = ChunkRepo(session)
            skipped_chunks = [await chunk_repo.get(cid) for cid in skip_ids]
        need_verify = [c.id for c in skipped_chunks if c and c.status == "synth_done"]
        if need_verify:
            p2v_futures = p2v_verify.map(need_verify, [language] * len(need_verify))
            [await f.result() for f in p2v_futures]
            log.info("P2v (skipped chunks): %d verified", len(need_verify))

    # Determine which chunks are verified and eligible for P5/P6.
    async with _session_factory() as session:
        chunk_repo = ChunkRepo(session)
        refreshed = await chunk_repo.list_by_episode(episode_id)
    verified_ids = [c.id for c in refreshed if c.status == "verified" and c.id in set(all_ids)]

    if not verified_ids:
        log.warning("No verified chunks — skipping P5/P6")
        return {
            "mode": "synthesize",
            "synthesized": len(need_p2_ids),
            "skipped_p2": len(skip_p2),
            "verified": 0,
            "needs_review": needs_review_count,
            "total": len(all_ids),
        }

    # P5: subtitles for verified chunks only.
    p5_futures = p5_subtitles.map(verified_ids)
    [await f.result() for f in p5_futures]
    log.info("P5 complete: %d subtitles", len(verified_ids))

    # P6: concat (always runs on full episode, not just targets)
    p6_result: P6Result = await p6_concat(episode_id, padding_ms=padding_ms, shot_gap_ms=shot_gap_ms)
    log.info("P6 complete: %s", p6_result.wav_uri)

    # P6v: end-to-end validation gate
    p6v_result = await p6v_check(
        episode_id,
        srt_uri=p6_result.srt_uri,
        total_duration_s=p6_result.total_duration_s,
    )
    log.info("P6v complete: status=%s", p6v_result["status"])

    return {
        "mode": "synthesize",
        "synthesized": len(need_p2_ids),
        "skipped_p2": len(skip_p2),
        "verified": len(verified_ids),
        "needs_review": needs_review_count,
        "total": len(all_ids),
    }


async def _run_retry_failed(
    episode_id: str,
    language: str,
    padding_ms: int,
    shot_gap_ms: int,
) -> dict[str, Any]:
    """Mode: retry_failed — Only re-run chunks with status='failed' or 'needs_review'."""
    from server.flows.worker_bootstrap import bootstrap, _session_factory

    if _session_factory is None:
        bootstrap()

    from server.core.repositories import ChunkRepo, EpisodeRepo
    async with _session_factory() as session:  # type: ignore[misc]
        chunk_repo = ChunkRepo(session)
        all_chunks = await chunk_repo.list_by_episode(episode_id)
        ep_repo = EpisodeRepo(session)
        ep = await ep_repo.get(episode_id)
        ep_config = (ep.config if ep else None) or {}

    tts_config = {k: v for k, v in ep_config.items() if k != "repair"}

    retry_targets = [c for c in all_chunks if c.status in ("failed", "needs_review")]
    if not retry_targets:
        log.info("No failed/needs_review chunks to retry")
        return {"mode": "retry_failed", "retried": 0}

    retry_ids = [c.id for c in retry_targets]
    log.info("Retrying %d failed/needs_review chunks", len(retry_ids))

    # P1c: input validation for retry chunks
    p1c_futures = p1c_check.map(retry_ids)
    [await f.result() for f in p1c_futures]

    p2_params = tts_config if tts_config else {}
    loop_tasks = [
        _synth_one_chunk(
            episode_id=episode_id,
            chunk_id=cid,
            base_params=p2_params,
            language=language,
        )
        for cid in retry_ids
    ]
    await asyncio.gather(*loop_tasks)

    # P5 for verified chunks.
    async with _session_factory() as session:
        chunk_repo = ChunkRepo(session)
        refreshed = await chunk_repo.list_by_episode(episode_id)
    verified_ids = [c.id for c in refreshed if c.status == "verified"]

    if verified_ids:
        p5_futures = p5_subtitles.map(verified_ids)
        [await f.result() for f in p5_futures]

    # P6: re-concat full episode
    p6_result = await p6_concat(episode_id, padding_ms=padding_ms, shot_gap_ms=shot_gap_ms)
    log.info("P6 complete after retry: %s", p6_result.wav_uri)

    # P6v: end-to-end validation
    await p6v_check(
        episode_id,
        srt_uri=p6_result.srt_uri,
        total_duration_s=p6_result.total_duration_s,
    )

    return {"mode": "retry_failed", "retried": len(retry_ids)}


async def _run_regenerate(
    episode_id: str,
    language: str,
    padding_ms: int,
    shot_gap_ms: int,
) -> dict[str, Any]:
    """Mode: regenerate — Clear everything, re-run P1→P2→P2v→P5→P6."""
    from server.flows.worker_bootstrap import get_p1_context, bootstrap, _session_factory

    if _session_factory is None:
        bootstrap()

    # Read episode config for P2 params
    from server.core.repositories import EpisodeRepo, ChunkRepo
    async with _session_factory() as session:  # type: ignore[misc]
        ep_repo = EpisodeRepo(session)
        ep = await ep_repo.get(episode_id)
        ep_config = (ep.config if ep else None) or {}

    tts_config = {k: v for k, v in ep_config.items() if k != "repair"}

    # P1 clears chunks (DELETE + bulk_insert)
    ctx = get_p1_context()
    p1_result = await p1_chunk(episode_id, ctx=ctx)
    chunk_ids = [c.id for c in p1_result.chunks]
    log.info("P1 regenerated: %d chunks", len(chunk_ids))

    # P1c: input validation
    p1c_futures = p1c_check.map(chunk_ids)
    [await f.result() for f in p1c_futures]

    p2_params = tts_config if tts_config else {}
    loop_tasks = [
        _synth_one_chunk(
            episode_id=episode_id,
            chunk_id=cid,
            base_params=p2_params,
            language=language,
        )
        for cid in chunk_ids
    ]
    await asyncio.gather(*loop_tasks)

    # P5 for verified chunks only.
    async with _session_factory() as session:
        chunk_repo = ChunkRepo(session)
        refreshed = await chunk_repo.list_by_episode(episode_id)
    verified_ids = [c.id for c in refreshed if c.status == "verified"]

    if verified_ids:
        p5_futures = p5_subtitles.map(verified_ids)
        [await f.result() for f in p5_futures]

    p6_result = await p6_concat(episode_id, padding_ms=padding_ms, shot_gap_ms=shot_gap_ms)

    # P6v: end-to-end validation
    await p6v_check(
        episode_id,
        srt_uri=p6_result.srt_uri,
        total_duration_s=p6_result.total_duration_s,
    )

    return {
        "mode": "regenerate",
        "chunk_count": len(chunk_ids),
        "verified": len(verified_ids),
        "wav_uri": p6_result.wav_uri,
    }


__all__ = ["run_episode_flow", "_synth_one_chunk"]
