"""P1 — script segmentation Prefect task.

Reads an episode's ``script.json`` from object storage, splits every segment
into sentences via :func:`server.core.p1_logic.script_to_chunks`, persists
the resulting rows through :class:`ChunkRepo`, writes framing events, and
transitions the episode into the ``ready`` state.

Design notes
------------
* The task is purely an I/O adapter over ``p1_logic``. All segmentation
  rules live in the pure logic module so they are unit-testable without a
  database, MinIO, or Prefect runtime.
* The task is **re-runnable**: if the ``chunks`` table already has rows for
  the episode, they are deleted inside the same transaction before the new
  bulk insert. This is what the prompt calls the "recommended" replay
  strategy. Combined with deterministic ``boundary_hash``, a clean P1
  re-run produces byte-identical output.
* ``stage_started`` is written *before* the logic runs, ``stage_finished``
  *after*. A mid-task failure leaves the ``stage_started`` event in place
  (as part of a rolled-back transaction, if we get that far — see below)
  and lets the Prefect task state machine decide whether to retry.
* Transaction boundary: everything except the MinIO read happens inside a
  single ``AsyncSession`` transaction, so partial writes are impossible.
  The MinIO read is best-effort; if the object is missing we raise
  :class:`DomainError` before touching the DB.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from prefect import task
from prefect.exceptions import MissingContextError
from prefect.logging.loggers import get_run_logger
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from server.core.domain import P1Result
from server.core.events import write_event
from server.core.models import Chunk
from server.core.p1_logic import script_to_chunks, DEFAULT_MAX_CHUNK_CHARS
from server.core.domain import DomainError
from server.core.repositories import ChunkRepo, EpisodeRepo
from server.core.storage import MinIOStorage, episode_script_key


@dataclass(frozen=True)
class P1Context:
    """Everything the task needs that is not episode-specific.

    Keeping these out of the function signature means Prefect runs don't
    need to serialise live DB / MinIO clients. In production W3 this will
    be wired up by the flow entry point; in unit tests we construct one
    directly with in-memory adapters.
    """

    session_maker: async_sessionmaker[AsyncSession]
    storage: MinIOStorage


async def _load_script(storage: MinIOStorage, episode_id: str) -> dict[str, Any]:
    key = episode_script_key(episode_id)
    try:
        raw = await storage.download_bytes(key)
    except Exception as exc:  # noqa: BLE001 — we re-raise as DomainError
        raise DomainError("not_found", f"script not found: {key}") from exc

    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DomainError("invalid_input", f"script is not valid JSON: {exc}") from exc

    if not isinstance(parsed, dict):
        raise DomainError(
            "invalid_input",
            f"script root must be an object, got {type(parsed).__name__}",
        )
    return parsed


async def _emit_stage_failed(
    session_maker: async_sessionmaker[AsyncSession],
    *,
    episode_id: str,
    error: str,
) -> None:
    """Best-effort stage_failed event write — never masks the real error."""
    try:
        async with session_maker() as session:
            async with session.begin():
                await write_event(
                    session,
                    episode_id=episode_id,
                    chunk_id=None,
                    kind="stage_failed",
                    payload={"stage": "p1", "error": error},
                )
    except Exception:  # pragma: no cover
        logging.getLogger(__name__).exception(
            "failed to emit stage_failed event for episode %s", episode_id
        )


async def _run_p1(
    ctx: P1Context,
    episode_id: str,
    *,
    max_chunk_chars: int = DEFAULT_MAX_CHUNK_CHARS,
) -> P1Result:
    try:
        script = await _load_script(ctx.storage, episode_id)
    except Exception as exc:
        await _emit_stage_failed(
            ctx.session_maker, episode_id=episode_id, error=str(exc)
        )
        raise

    try:
        chunks = script_to_chunks(script, episode_id, max_chunk_chars=max_chunk_chars)
    except ValueError as exc:
        await _emit_stage_failed(
            ctx.session_maker, episode_id=episode_id, error=str(exc)
        )
        raise DomainError("invalid_input", str(exc)) from exc

    async with ctx.session_maker() as session:
        try:
            async with session.begin():
                ep_repo = EpisodeRepo(session)
                chunk_repo = ChunkRepo(session)

                episode = await ep_repo.get(episode_id)
                if episode is None:
                    raise DomainError("not_found", f"episode not found: {episode_id}")

                # stage_started — before any mutating work, so consumers see the
                # pipeline move even if we end up raising later in the tx.
                await write_event(
                    session,
                    episode_id=episode_id,
                    chunk_id=None,
                    kind="stage_started",
                    payload={"stage": "p1"},
                )

                # Clean slate: a re-run drops stale rows before inserting the
                # newly-computed ones. We do this via a direct delete() so it is
                # a single SQL statement inside the current transaction.
                await session.execute(delete(Chunk).where(Chunk.episode_id == episode_id))

                inserted = await chunk_repo.bulk_insert(chunks)

                # NB: p1_chunk does not manage episode-level status. Doing so
                # was the root cause of a nasty bug — when this task ran as
                # the first step of a regenerate pipeline it would flip
                # episode.status back to "ready" while P2-P6 were still
                # executing, which broke the UI's "running → show cancel
                # button" contract. The owner of episode.status is the
                # orchestration layer (the /run API route for dev runs, or
                # the Prefect flow for production runs), which knows the
                # whole pipeline's shape and terminal state.

                await write_event(
                    session,
                    episode_id=episode_id,
                    chunk_id=None,
                    kind="stage_finished",
                    payload={"stage": "p1", "chunk_count": inserted},
                )
        except Exception as exc:
            await _emit_stage_failed(
                ctx.session_maker, episode_id=episode_id, error=str(exc)
            )
            raise

    return P1Result(episode_id=episode_id, chunks=chunks)


@task(name="p1-chunk")
async def p1_chunk(
    episode_id: str,
    *,
    ctx: P1Context,
    max_chunk_chars: int = DEFAULT_MAX_CHUNK_CHARS,
) -> P1Result:
    """Prefect task: run P1 segmentation for ``episode_id``.

    The task takes its runtime dependencies via an explicit ``ctx`` keyword
    rather than a module-level singleton so that unit tests and the W3 flow
    entry point can pass in their own sessions / storage without monkey
    patching. Prefect does not serialize the ctx — it's used only inside
    the task body.
    """
    try:
        logger = get_run_logger()
    except MissingContextError:
        # Called outside a Prefect flow/task runtime (e.g. direct unit test
        # invocation via ``p1_chunk.fn``). Fall back to stdlib logging so
        # the adapter stays fully usable in tests.
        logger = logging.getLogger("server.flows.tasks.p1_chunk")
    logger.info("P1 starting (max_chunk_chars=%d)", max_chunk_chars, extra={"episode_id": episode_id})
    result = await _run_p1(ctx, episode_id, max_chunk_chars=max_chunk_chars)
    logger.info(
        "P1 finished",
        extra={"episode_id": episode_id, "chunk_count": len(result.chunks)},
    )
    return result


__all__ = ["p1_chunk", "P1Context", "DomainError"]
