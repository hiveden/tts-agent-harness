"""retry-chunk-stage — mini flow for single-chunk partial re-run.

Supports two modes:

- ``cascade=True`` (default): run from ``from_stage`` through all
  downstream stages. E.g. ``from_stage="p2"`` runs P2 → P2v → P5;
  P6 is NOT included because it is per-episode, not per-chunk.

- ``cascade=False``: run only ``from_stage``, then mark downstream
  ``stage_runs`` as ``stale`` so the operator knows they need re-running.

Stage ordering: p2 → p2v → p5 (per-chunk stages only).
``p3`` is accepted as an alias for ``p2v`` for backward compatibility.
P1 is per-episode and is not retryable via this flow.
P6 is per-episode and must be triggered separately after all chunks are ready.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from prefect import flow

from server.core.domain import P2Result, P2vResult, P5Result

log = logging.getLogger(__name__)

# Ordered list of per-chunk stages.
CHUNK_STAGES = ["p2", "p2v", "p5"]

# Backward-compat alias: callers using "p3" get mapped to "p2v".
_STAGE_ALIASES = {"p3": "p2v"}


@flow(name="retry-chunk-stage")
async def retry_chunk_stage_flow(
    ep_id: str,
    cid: str,
    from_stage: str,
    cascade: bool = True,
    language: str = "zh",
) -> dict:
    """Re-run a single chunk from ``from_stage`` onward.

    Parameters
    ----------
    ep_id
        Episode ID (used for logging / event context).
    cid
        Chunk ID to re-process.
    from_stage
        Stage to start from (``"p2"``, ``"p3"``, or ``"p5"``).
    cascade
        If True, run all downstream stages after ``from_stage``.
        If False, only run ``from_stage`` and mark downstream as stale.
    language
        Language code for P3.
    """
    # Map legacy aliases (e.g. "p3" -> "p2v").
    from_stage = _STAGE_ALIASES.get(from_stage, from_stage)

    if from_stage not in CHUNK_STAGES:
        raise ValueError(
            f"from_stage must be one of {CHUNK_STAGES}, got {from_stage!r}"
        )

    start_idx = CHUNK_STAGES.index(from_stage)
    stages_to_run = CHUNK_STAGES[start_idx:] if cascade else [from_stage]

    results: dict = {}
    log.info(
        "retry-chunk-stage: ep=%s cid=%s from=%s cascade=%s stages=%s",
        ep_id, cid, from_stage, cascade, stages_to_run,
    )

    for stage in stages_to_run:
        if stage == "p2":
            from server.flows.tasks.p2_synth import p2_synth

            result: P2Result = await p2_synth(cid)
            results["p2"] = result
        elif stage == "p2v":
            from server.flows.tasks.p2v_verify import p2v_verify

            result: P2vResult = await p2v_verify(cid, language=language)
            results["p2v"] = result
        elif stage == "p5":
            from server.flows.tasks.p5_subtitles import p5_subtitles

            result: P5Result = await p5_subtitles(cid)
            results["p5"] = result

    # If not cascading, mark downstream stages as stale.
    if not cascade:
        downstream = CHUNK_STAGES[start_idx + 1:]
        if downstream:
            await _mark_downstream_stale(cid, downstream)
            results["stale_stages"] = downstream

    return results


async def _mark_downstream_stale(chunk_id: str, stages: list[str]) -> None:
    """Mark stage_runs as stale for downstream stages.

    This is a best-effort operation using the module-level DI pattern.
    """
    from server.flows.tasks.p2v_verify import _require_deps, _session_scope

    try:
        session_factory, _ = _require_deps()
    except RuntimeError:
        log.warning("Cannot mark stale: dependencies not configured")
        return

    from server.core.repositories import StageRunRepo

    async with _session_scope(session_factory) as session:
        repo = StageRunRepo(session)
        for stage in stages:
            existing = await repo.get(chunk_id, stage)
            if existing is not None:
                await repo.upsert(
                    chunk_id=chunk_id,
                    stage=stage,
                    status=existing.status,
                    stale=True,
                )
        await session.commit()

    log.info("Marked %s as stale for chunk %s", stages, chunk_id)


__all__ = ["retry_chunk_stage_flow"]
