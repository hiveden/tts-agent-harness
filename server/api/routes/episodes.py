"""Episode + chunk routes.

All business logic is delegated to repositories. Route handlers are thin:
validate input → call repo → return response model.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from typing import Any

# In-flight run tasks — cancel support
_running_tasks: dict[str, asyncio.Task] = {}  # episode_id → Task

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from minio.error import S3Error
from pydantic import BaseModel
from server.core.domain import _CamelBase
from sqlalchemy import func as sa_func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.core.domain import (
    ChunkEdit,
    ChunkView,
    DomainError,
    EpisodeCreate,
    EpisodeSummary,
    EpisodeView,
    StageRunView,
    TakeView,
)
from server.core.repositories import (
    ChunkRepo,
    EpisodeRepo,
    EventRepo,
    StageRunRepo,
    TakeRepo,
)
from server.core.models import Event
from server.core.storage import MinIOStorage, episode_script_key
from server.api.deps import get_prefect_client, get_session, get_storage

router = APIRouter(tags=["episodes"])


# ---------------------------------------------------------------------------
# Response schemas (API-specific wrappers around domain views)
# ---------------------------------------------------------------------------


class ChunkDetail(ChunkView):
    """ChunkView extended with nested takes and stage_runs."""

    takes: list[TakeView] = []
    stage_runs: list[StageRunView] = []
    verify_scores: dict[str, float] | None = None
    verify_diagnosis: dict[str, Any] | None = None


class EpisodeDetail(EpisodeView):
    """EpisodeView extended with nested chunks."""

    chunks: list[ChunkDetail] = []


class RunResponse(_CamelBase):
    flow_run_id: str


class RetryResponse(_CamelBase):
    flow_run_id: str


class FinalizeResponse(_CamelBase):
    flow_run_id: str


class EditResponse(_CamelBase):
    updated: int


class DeleteResponse(_CamelBase):
    deleted: bool


class LockResponse(_CamelBase):
    locked: bool


class DuplicateRequest(_CamelBase):
    new_id: str


class ArchiveResponse(_CamelBase):
    archived_at: datetime


class ChunkLogResponse(_CamelBase):
    content: str
    stage: str
    chunk_id: str


class EpisodeLogsResponse(_CamelBase):
    lines: list[str]


class ConfigUpdateRequest(_CamelBase):
    config: dict[str, Any]


class ConfigResponse(_CamelBase):
    config: dict[str, Any]


class RunRequest(_CamelBase):
    """Optional body for POST /episodes/{id}/run."""

    mode: str = "synthesize"  # "chunk_only" | "synthesize" | "retry_failed" | "regenerate"
    chunk_ids: list[str] | None = None  # for multi-select; None = all


# ---------------------------------------------------------------------------
# GET /episodes
# ---------------------------------------------------------------------------


@router.get("/episodes", response_model=list[EpisodeSummary])
async def list_episodes(
    include_archived: bool = False,
    session: AsyncSession = Depends(get_session),
) -> list[EpisodeSummary]:
    repo = EpisodeRepo(session)
    chunk_repo = ChunkRepo(session)
    episodes = await repo.list(include_archived=include_archived)
    result: list[EpisodeSummary] = []
    for ep in episodes:
        chunks = await chunk_repo.list_by_episode(ep.id)
        done_count = sum(1 for c in chunks if c.status == "done")
        failed_count = sum(1 for c in chunks if c.status == "failed")
        result.append(
            EpisodeSummary(
                id=ep.id,
                title=ep.title,
                status=ep.status,
                locked=ep.locked,
                chunk_count=len(chunks),
                done_count=done_count,
                failed_count=failed_count,
                updated_at=ep.updated_at,
            )
        )
    return result


# ---------------------------------------------------------------------------
# POST /episodes
# ---------------------------------------------------------------------------


@router.post("/episodes", response_model=EpisodeView, status_code=201)
async def create_episode(
    id: str = Form(...),
    title: str = Form(""),
    description: str = Form(None),
    config: str = Form("{}"),
    script: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    storage: MinIOStorage = Depends(get_storage),
) -> EpisodeView:
    # Upload script to MinIO
    script_bytes = await script.read()

    # Validate JSON
    try:
        json.loads(script_bytes)
    except json.JSONDecodeError as exc:
        raise DomainError("invalid_input", f"script is not valid JSON: {exc}")

    key = episode_script_key(id)
    script_uri = await storage.upload_bytes(key, script_bytes, "application/json")

    # Parse config
    try:
        config_dict = json.loads(config)
    except json.JSONDecodeError:
        config_dict = {}

    repo = EpisodeRepo(session)

    # Check for duplicate
    existing = await repo.get(id)
    if existing is not None:
        raise DomainError("invalid_input", f"episode '{id}' already exists")

    payload = EpisodeCreate(
        id=id,
        title=title or id,
        description=description,
        script_uri=script_uri,
        config=config_dict,
    )
    ep = await repo.create(payload)

    # Write event
    event_repo = EventRepo(session)
    await event_repo.write(
        episode_id=ep.id,
        chunk_id=None,
        kind="episode_created",
        payload={"title": ep.title},
    )

    await session.commit()

    # Trigger storage cleanup in background (best-effort)
    import asyncio
    from server.core.cleanup import cleanup_if_needed
    from server.core.db import get_sessionmaker
    asyncio.create_task(cleanup_if_needed(get_sessionmaker(), storage))

    return EpisodeView.model_validate(ep)


# ---------------------------------------------------------------------------
# GET /episodes/{id}
# ---------------------------------------------------------------------------


@router.get("/episodes/{episode_id}", response_model=EpisodeDetail)
async def get_episode(
    episode_id: str,
    session: AsyncSession = Depends(get_session),
) -> EpisodeDetail:
    repo = EpisodeRepo(session)
    ep = await repo.get(episode_id)
    if ep is None:
        raise DomainError("not_found", f"episode '{episode_id}' not found")

    chunk_repo = ChunkRepo(session)
    take_repo = TakeRepo(session)
    sr_repo = StageRunRepo(session)

    chunks = await chunk_repo.list_by_episode(episode_id)

    # Batch-query latest verify event per chunk (avoid N+1)
    chunk_ids = [c.id for c in chunks]
    verify_map: dict[str, Event] = {}
    if chunk_ids:
        # Subquery: max event id per chunk for verify_finished/verify_failed
        latest_ids_sq = (
            select(
                Event.chunk_id,
                sa_func.max(Event.id).label("max_id"),
            )
            .where(
                Event.chunk_id.in_(chunk_ids),
                Event.kind.in_(["verify_finished", "verify_failed"]),
            )
            .group_by(Event.chunk_id)
            .subquery()
        )
        result = await session.execute(
            select(Event).join(
                latest_ids_sq,
                Event.id == latest_ids_sq.c.max_id,
            )
        )
        for ev in result.scalars():
            if ev.chunk_id:
                verify_map[ev.chunk_id] = ev

    chunk_details: list[ChunkDetail] = []
    for c in chunks:
        takes = await take_repo.list_by_chunk(c.id)
        stage_runs = await sr_repo.list_by_chunk(c.id)
        # Build from dict to avoid lazy-load issues on ORM relationships.
        # Defensive: map legacy status values to prevent Pydantic validation errors.
        _STATUS_COMPAT = {"transcribed": "verified"}
        chunk_status = _STATUS_COMPAT.get(c.status, c.status)
        chunk_dict = {
            "id": c.id,
            "episode_id": c.episode_id,
            "shot_id": c.shot_id,
            "idx": c.idx,
            "text": c.text,
            "text_normalized": c.text_normalized,
            "subtitle_text": c.subtitle_text,
            "status": chunk_status,
            "selected_take_id": c.selected_take_id,
            "boundary_hash": c.boundary_hash,
            "char_count": c.char_count,
            "last_edited_at": c.last_edited_at,
            "extra_metadata": c.extra_metadata,
            "takes": [TakeView.model_validate(t) for t in takes],
            "stage_runs": [StageRunView.model_validate(sr) for sr in stage_runs],
        }
        ve = verify_map.get(c.id)
        if ve:
            chunk_dict["verify_scores"] = ve.payload.get("scores")
            chunk_dict["verify_diagnosis"] = ve.payload.get("diagnosis")
        chunk_details.append(ChunkDetail(**chunk_dict))

    # Build from dict to avoid lazy-load on Episode.chunks relationship
    ep_dict = {
        "id": ep.id,
        "title": ep.title,
        "description": ep.description,
        "status": ep.status,
        "script_uri": ep.script_uri,
        "config": ep.config,
        "locked": ep.locked,
        "created_at": ep.created_at,
        "updated_at": ep.updated_at,
        "archived_at": ep.archived_at,
        "extra_metadata": ep.extra_metadata,
        "chunks": chunk_details,
    }
    return EpisodeDetail(**ep_dict)


# ---------------------------------------------------------------------------
# DELETE /episodes/{id}
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# GET/PUT /episodes/{id}/config
# ---------------------------------------------------------------------------


@router.get("/episodes/{episode_id}/config", response_model=ConfigResponse)
async def get_config(
    episode_id: str,
    session: AsyncSession = Depends(get_session),
) -> ConfigResponse:
    repo = EpisodeRepo(session)
    ep = await repo.get(episode_id)
    if ep is None:
        raise DomainError("not_found", f"episode '{episode_id}' not found")
    return ConfigResponse(config=ep.config or {})


@router.put("/episodes/{episode_id}/config", response_model=ConfigResponse)
async def update_config(
    episode_id: str,
    body: ConfigUpdateRequest,
    session: AsyncSession = Depends(get_session),
) -> ConfigResponse:
    repo = EpisodeRepo(session)
    ep = await repo.get(episode_id)
    if ep is None:
        raise DomainError("not_found", f"episode '{episode_id}' not found")
    # Merge: body.config overwrites existing keys
    merged = {**(ep.config or {}), **body.config}
    from sqlalchemy import update
    from server.core.models import Episode as EpisodeModel
    await session.execute(
        update(EpisodeModel)
        .where(EpisodeModel.id == episode_id)
        .values(config=merged)
    )
    event_repo = EventRepo(session)
    await event_repo.write(
        episode_id=episode_id,
        chunk_id=None,
        kind="config_updated",
        payload={"config": merged},
    )
    await session.commit()
    return ConfigResponse(config=merged)


# ---------------------------------------------------------------------------
# DELETE /episodes/{id}
# ---------------------------------------------------------------------------


@router.delete("/episodes/{episode_id}", response_model=DeleteResponse)
async def delete_episode(
    episode_id: str,
    session: AsyncSession = Depends(get_session),
) -> DeleteResponse:
    repo = EpisodeRepo(session)
    ep = await repo.get(episode_id)
    if ep is None:
        raise DomainError("not_found", f"episode '{episode_id}' not found")
    if ep.locked:
        raise DomainError("invalid_state", f"episode '{episode_id}' is locked")
    deleted = await repo.delete(episode_id)
    if not deleted:
        raise DomainError("not_found", f"episode '{episode_id}' not found")
    await session.commit()
    return DeleteResponse(deleted=True)


# ---------------------------------------------------------------------------
# POST /episodes/{id}/run
# ---------------------------------------------------------------------------


@router.post("/episodes/{episode_id}/run", response_model=RunResponse)
async def run_episode(
    episode_id: str,
    request: Request,
    body: RunRequest | None = None,
    session: AsyncSession = Depends(get_session),
    prefect_client: Any = Depends(get_prefect_client),
) -> RunResponse:
    """Trigger episode pipeline.

    Modes (D-03 product design):
    - "chunk_only": Only P1 (split script into chunks). For empty episodes.
    - "synthesize": P2→P3→P5→P6 for chunks without selected_take (skip confirmed).
                    Default mode. Reads episode.config for TTS params.
    - "retry_failed": Only re-run chunks with status="failed", from their failed stage.
    - "regenerate": Clear all chunks/takes, re-run P1→P2→P3→P5→P6. Needs confirmation.

    chunk_ids: Optional list. If provided, only run these chunks (multi-select).
    """
    from server.core.crypto import decrypt_value

    fish_key_enc = request.cookies.get("__fish_key")
    try:
        x_fish_key = decrypt_value(fish_key_enc) if fish_key_enc else None
    except Exception:
        x_fish_key = None
    groq_key_enc = request.cookies.get("__groq_key")
    try:
        x_groq_key = decrypt_value(groq_key_enc) if groq_key_enc else None
    except Exception:
        x_groq_key = None

    mode = (body.mode if body else None) or "synthesize"
    chunk_ids = body.chunk_ids if body else None

    # Atomic status check: SELECT FOR UPDATE prevents concurrent runs
    from server.core.models import Episode as EpisodeModel
    stmt = (
        select(EpisodeModel)
        .where(EpisodeModel.id == episode_id)
        .with_for_update(nowait=True)
    )
    try:
        result = await session.execute(stmt)
    except Exception:
        raise DomainError("invalid_state", "episode is locked by another operation")
    ep = result.scalar_one_or_none()
    if ep is None:
        raise DomainError("not_found", f"episode '{episode_id}' not found")

    if ep.locked:
        raise DomainError("invalid_state", f"episode '{episode_id}' is locked")

    if ep.status == "running":
        raise DomainError("invalid_state", "episode is already running")

    # Try Prefect deployment first; fall back to in-process execution (dev mode)
    import asyncio
    import uuid
    use_prefect = os.environ.get("TTS_USE_PREFECT", "").lower() in ("1", "true", "yes")

    flow_run_id = str(uuid.uuid4())

    if use_prefect:
        flow_run = await prefect_client.create_flow_run_from_deployment(
            "run-episode/run-episode",
            parameters={
                "episode_id": episode_id,
                "mode": mode,
                "chunk_ids": chunk_ids,
            },
        )
        flow_run_id = str(flow_run.id)
    else:
        # Dev mode: run flow in-process as a background task
        from server.flows.worker_bootstrap import bootstrap as _bootstrap
        _bootstrap()

        # Resolve Fish API key for modes that use P2 (not chunk_only)
        if mode != "chunk_only":
            fish_key = x_fish_key or os.environ.get("FISH_TTS_KEY", "")
            if not fish_key:
                raise DomainError("auth_required", "Fish API Key 未配置。请在设置中填入 API Key。")
            # Re-configure P2 with the resolved key (may differ from env var)
            from server.flows.tasks.p2_synth import configure_p2_dependencies
            from server.core.fish_client import FishTTSClient
            from server.flows.worker_bootstrap import _session_factory, _storage
            configure_p2_dependencies(
                session_factory=_session_factory,
                storage=_storage,
                fish_client_factory=lambda: FishTTSClient(api_key=fish_key),
            )

            # Re-configure P2v with Groq key (if available)
            groq_key = x_groq_key or os.environ.get("GROQ_API_KEY", "")
            from server.flows.tasks.p2v_verify import configure_p2v_dependencies
            configure_p2v_dependencies(
                session_factory=_session_factory,
                storage=_storage,
                whisperx_url=os.environ.get("WHISPERX_URL", "http://localhost:7860"),
                groq_api_key=groq_key or None,
                groq_proxy=os.environ.get("HTTPS_PROXY"),
            )

        async def _run_dev():
            """Dev mode: run pipeline stages directly (no Prefect decorators)."""
            import logging
            from datetime import datetime, timezone
            _log = logging.getLogger("dev_runner")

            async def _mark_stage(cid: str, stage: str, status: str, error: str | None = None, started: datetime | None = None, context: dict | None = None):
                """Write stage_run + event with execution context."""
                from server.core.repositories import StageRunRepo, EventRepo
                async with _session_factory() as s:
                    sr_repo = StageRunRepo(s)
                    existing = await sr_repo.get(cid, stage)
                    attempt = (existing.attempt + 1) if existing and status == "running" else (existing.attempt if existing else 1)
                    finished = datetime.now(timezone.utc) if status in ("ok", "failed") else None
                    duration_ms = int((finished - started).total_seconds() * 1000) if finished and started else None
                    await sr_repo.upsert(
                        chunk_id=cid, stage=stage, status=status,
                        attempt=attempt,
                        started_at=started, finished_at=finished,
                        duration_ms=duration_ms,
                        error=error,
                    )
                    # Write event with execution context (request/response params)
                    if context and status in ("ok", "failed"):
                        event_repo = EventRepo(s)
                        await event_repo.write(
                            episode_id=episode_id,
                            chunk_id=cid,
                            kind=f"stage_{status}",
                            payload={"stage": stage, "attempt": attempt, "durationMs": duration_ms, **context},
                        )
                    await s.commit()

            try:
                from server.core.repositories import ChunkRepo, EpisodeRepo
                from server.flows.worker_bootstrap import _session_factory, _storage

                if mode == "chunk_only":
                    from server.flows.worker_bootstrap import get_p1_context
                    from server.flows.tasks.p1_chunk import p1_chunk
                    ctx = get_p1_context()
                    result = await p1_chunk.fn(episode_id, ctx=ctx)
                    _log.info("P1 done: %d chunks", len(result.chunks))
                    return

                # synthesize / retry_failed / regenerate
                async with _session_factory() as sess:
                    all_chunks = await ChunkRepo(sess).list_by_episode(episode_id)
                    ep = await EpisodeRepo(sess).get(episode_id)
                    tts_config = (ep.config if ep else None) or {}

                target = list(all_chunks)
                if chunk_ids:
                    cid_set = set(chunk_ids)
                    target = [c for c in target if c.id in cid_set]

                if mode == "retry_failed":
                    target = [c for c in target if c.status == "failed"]

                if mode == "regenerate":
                    from server.flows.worker_bootstrap import get_p1_context
                    from server.flows.tasks.p1_chunk import p1_chunk
                    ctx = get_p1_context()
                    result = await p1_chunk.fn(episode_id, ctx=ctx)
                    target_ids = [c.id for c in result.chunks]
                    _log.info("P1 regenerated: %d chunks", len(target_ids))
                else:
                    target_ids = [c.id for c in target]

                # --- Helpers ---
                import asyncio as _aio

                async def _retry(fn, *args, retries=3, backoff=(2, 4, 8), **kwargs):
                    """Retry with exponential backoff."""
                    last = None
                    for attempt in range(1, retries + 1):
                        try:
                            return await fn(*args, **kwargs)
                        except Exception as e:
                            last = e
                            if attempt < retries:
                                delay = backoff[min(attempt - 1, len(backoff) - 1)]
                                _log.warning("Retry %d/%d for %s: %s (wait %ds)", attempt, retries, fn.__name__, e, delay)
                                await _aio.sleep(delay)
                    raise last  # type: ignore[misc]

                def _fmt_err(e: Exception) -> str:
                    msg = f"{type(e).__name__}: {e}" if str(e).strip() else type(e).__name__
                    return msg[:500] + "..." if len(msg) > 500 else msg

                async def _set_chunk_failed(cid: str, error: str):
                    async with _session_factory() as _s:
                        await ChunkRepo(_s).set_status(cid, "failed")
                        await _s.commit()

                failed_chunks: set[str] = set()

                # --- P2: synthesize (with retry, fault-isolated) ---
                from server.flows.tasks.p2_synth import run_p2_synth
                p2_params = tts_config if tts_config else None
                for cid in target_ids:
                    if mode == "synthesize":
                        chunk_obj = next((c for c in target if c.id == cid), None)
                        if chunk_obj and chunk_obj.status == "verified":
                            _log.info("P2 skip %s (verified)", cid)
                            await _mark_stage(cid, "p2", "ok", context={"skipped": True, "reason": "already verified"})
                            continue
                    async with _session_factory() as _s:
                        _chunk = await ChunkRepo(_s).get(cid)
                        _text = _chunk.text_normalized if _chunk else ""
                    _log.info("P2 synth %s", cid)
                    t0 = datetime.now(timezone.utc)
                    await _mark_stage(cid, "p2", "running", started=t0)
                    try:
                        p2_result = await _retry(run_p2_synth, cid, params=p2_params)
                        await _mark_stage(cid, "p2", "ok", started=t0, context={
                            "request": {"text": _text[:100], **(p2_params if isinstance(p2_params, dict) else {})},
                            "response": {"takeId": p2_result.take_id, "audioUri": p2_result.audio_uri, "durationS": p2_result.duration_s},
                        })
                    except Exception as e:
                        err_msg = _fmt_err(e)
                        _log.error("P2 failed %s: %s", cid, err_msg)
                        await _mark_stage(cid, "p2", "failed", error=err_msg, started=t0, context={
                            "request": {"text": _text[:100], **(p2_params if isinstance(p2_params, dict) else {})},
                        })
                        await _set_chunk_failed(cid, err_msg)
                        failed_chunks.add(cid)
                        continue  # Don't block other chunks

                # --- P2c: format check (skip failed) ---
                from server.flows.tasks.p2c_check import run_p2c_check
                for cid in target_ids:
                    if cid in failed_chunks:
                        continue
                    async with _session_factory() as _s:
                        _ch = await ChunkRepo(_s).get(cid)
                        if not _ch or not _ch.selected_take_id or _ch.status != "synth_done":
                            continue
                    _log.info("P2c check %s", cid)
                    t0 = datetime.now(timezone.utc)
                    await _mark_stage(cid, "p2c", "running", started=t0)
                    try:
                        p2c_result = await run_p2c_check(cid)
                        p2c_status = p2c_result.get("status", "ok") if isinstance(p2c_result, dict) else "ok"
                        if p2c_status == "failed":
                            err_msg = "; ".join(p2c_result.get("errors", []))
                            await _mark_stage(cid, "p2c", "failed", error=err_msg, started=t0)
                            await _set_chunk_failed(cid, err_msg)
                            failed_chunks.add(cid)
                        else:
                            await _mark_stage(cid, "p2c", "ok", started=t0, context={
                                "response": p2c_result if isinstance(p2c_result, dict) else {"status": "ok"},
                            })
                    except Exception as e:
                        err_msg = _fmt_err(e)
                        _log.error("P2c failed %s: %s", cid, err_msg)
                        await _mark_stage(cid, "p2c", "failed", error=err_msg, started=t0)
                        await _set_chunk_failed(cid, err_msg)
                        failed_chunks.add(cid)
                        continue

                # --- P2v: ASR verify (skip failed) ---
                from server.flows.tasks.p2v_verify import run_p2v_verify
                for cid in target_ids:
                    if cid in failed_chunks:
                        continue
                    async with _session_factory() as _s:
                        _ch = await ChunkRepo(_s).get(cid)
                        if not _ch or _ch.status != "synth_done":
                            continue
                    _log.info("P2v verify %s", cid)
                    t0 = datetime.now(timezone.utc)
                    await _mark_stage(cid, "p2v", "running", started=t0)
                    try:
                        p2v_result = await run_p2v_verify(cid)
                        await _mark_stage(cid, "p2v", "ok", started=t0, context={
                            "response": {"verdict": p2v_result.verdict, "charRatio": p2v_result.char_ratio, "transcriptUri": p2v_result.transcript_uri},
                        })
                    except Exception as e:
                        err_msg = _fmt_err(e)
                        _log.error("P2v failed %s: %s", cid, err_msg)
                        await _mark_stage(cid, "p2v", "failed", error=err_msg, started=t0)
                        await _set_chunk_failed(cid, err_msg)
                        failed_chunks.add(cid)
                        continue

                # --- P5: subtitles (only verified chunks) ---
                from server.flows.tasks.p5_subtitles import run_p5_subtitles
                for cid in target_ids:
                    if cid in failed_chunks:
                        continue
                    async with _session_factory() as _s:
                        _ch = await ChunkRepo(_s).get(cid)
                        if not _ch or _ch.status != "verified":
                            continue
                    _log.info("P5 subtitle %s", cid)
                    t0 = datetime.now(timezone.utc)
                    await _mark_stage(cid, "p5", "running", started=t0)
                    try:
                        p5_result = await run_p5_subtitles(cid)
                        await _mark_stage(cid, "p5", "ok", started=t0, context={
                            "response": {"subtitleUri": p5_result.subtitle_uri, "lineCount": p5_result.line_count},
                        })
                    except Exception as e:
                        err_msg = _fmt_err(e)
                        await _mark_stage(cid, "p5", "failed", error=err_msg, started=t0)
                        await _set_chunk_failed(cid, err_msg)
                        failed_chunks.add(cid)
                        continue

                # --- P6: concat (all verified chunks) ---
                from server.flows.tasks.p6_concat import run_p6_concat
                async with _session_factory() as sess:
                    _log.info("P6 concat %s", episode_id)
                    await run_p6_concat(episode_id, session=sess, storage=_storage)

                # --- Episode final status ---
                async with _session_factory() as sess:
                    final_chunks = await ChunkRepo(sess).list_by_episode(episode_id)
                    has_failed = any(c.status == "failed" for c in final_chunks)
                    if has_failed:
                        await EpisodeRepo(sess).set_status(episode_id, "failed")
                        _log.info("Episode %s → failed (%d chunk failures)", episode_id, len(failed_chunks))
                    else:
                        await EpisodeRepo(sess).set_status(episode_id, "done")
                        _log.info("Episode %s → done", episode_id)
                    await sess.commit()

            except Exception as exc:
                import logging
                logging.getLogger("dev_runner").error("flow failed: %s", exc, exc_info=True)
                try:
                    async with _session_factory() as sess:
                        await EpisodeRepo(sess).set_status(episode_id, "failed")
                        await sess.commit()
                except Exception:
                    pass

        task = asyncio.create_task(_run_dev())
        _running_tasks[episode_id] = task
        task.add_done_callback(lambda _: _running_tasks.pop(episode_id, None))

    await EpisodeRepo(session).set_status(episode_id, "running")

    event_repo = EventRepo(session)
    await event_repo.write(
        episode_id=episode_id,
        chunk_id=None,
        kind="episode_status_changed",
        payload={"status": "running", "mode": mode},
    )
    await session.commit()

    return RunResponse(flow_run_id=flow_run_id)


# ---------------------------------------------------------------------------
# POST /episodes/{id}/chunks/{cid}/edit
# ---------------------------------------------------------------------------


@router.post(
    "/episodes/{episode_id}/chunks/{chunk_id}/edit",
    response_model=EditResponse,
)
async def edit_chunk(
    episode_id: str,
    chunk_id: str,
    text_normalized: str | None = None,
    subtitle_text: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> EditResponse:
    # Check locked
    ep_repo = EpisodeRepo(session)
    ep = await ep_repo.get(episode_id)
    if ep is None:
        raise DomainError("not_found", f"episode '{episode_id}' not found")
    if ep.locked:
        raise DomainError("invalid_state", f"episode '{episode_id}' is locked")

    chunk_repo = ChunkRepo(session)

    # Verify chunk exists and belongs to the episode
    chunk = await chunk_repo.get(chunk_id)
    if chunk is None or chunk.episode_id != episode_id:
        raise DomainError("not_found", f"chunk '{chunk_id}' not found in episode '{episode_id}'")

    edit = ChunkEdit(
        chunk_id=chunk_id,
        text_normalized=text_normalized,
        subtitle_text=subtitle_text,
    )
    updated = await chunk_repo.apply_edits([edit])

    event_repo = EventRepo(session)
    await event_repo.write(
        episode_id=episode_id,
        chunk_id=chunk_id,
        kind="chunk_edited",
        payload={"text_normalized": text_normalized, "subtitle_text": subtitle_text},
    )
    await session.commit()

    return EditResponse(updated=updated)


# ---------------------------------------------------------------------------
# POST /episodes/{id}/chunks/{cid}/retry
# ---------------------------------------------------------------------------


@router.post(
    "/episodes/{episode_id}/chunks/{chunk_id}/retry",
    response_model=RetryResponse,
)
async def retry_chunk(
    episode_id: str,
    chunk_id: str,
    request: Request,
    from_stage: str = "p2",
    cascade: bool = True,
    session: AsyncSession = Depends(get_session),
    prefect_client: Any = Depends(get_prefect_client),
) -> RetryResponse:
    from server.core.crypto import decrypt_value

    fish_key_enc = request.cookies.get("__fish_key")
    try:
        x_fish_key = decrypt_value(fish_key_enc) if fish_key_enc else None
    except Exception:
        x_fish_key = None
    groq_key_enc = request.cookies.get("__groq_key")
    try:
        x_groq_key = decrypt_value(groq_key_enc) if groq_key_enc else None
    except Exception:
        x_groq_key = None

    chunk_repo = ChunkRepo(session)
    chunk = await chunk_repo.get(chunk_id)
    if chunk is None or chunk.episode_id != episode_id:
        raise DomainError("not_found", f"chunk '{chunk_id}' not found in episode '{episode_id}'")

    import asyncio, uuid
    use_prefect = os.environ.get("TTS_USE_PREFECT", "").lower() in ("1", "true", "yes")
    flow_run_id = str(uuid.uuid4())

    if use_prefect:
        flow_run = await prefect_client.create_flow_run_from_deployment(
            "retry-chunk-stage/retry-chunk-stage",
            parameters={
                "episode_id": episode_id,
                "chunk_id": chunk_id,
                "from_stage": from_stage,
                "cascade": cascade,
            },
        )
        flow_run_id = str(flow_run.id)
    else:
        from server.flows.worker_bootstrap import bootstrap as _bootstrap
        from datetime import datetime, timezone
        _bootstrap()

        # Resolve Fish API key for P2 stage
        if from_stage == "p2":
            fish_key = x_fish_key or os.environ.get("FISH_TTS_KEY", "")
            if not fish_key:
                raise DomainError("auth_required", "Fish API Key 未配置。请在设置中填入 API Key。")
            from server.flows.tasks.p2_synth import configure_p2_dependencies
            from server.core.fish_client import FishTTSClient
            from server.flows.worker_bootstrap import _session_factory as _sf, _storage as _st
            configure_p2_dependencies(
                session_factory=_sf,
                storage=_st,
                fish_client_factory=lambda: FishTTSClient(api_key=fish_key),
            )

        # Re-configure P2v with Groq key for stages that use ASR
        if from_stage in ("p2", "p2v", "p3"):
            from server.flows.tasks.p2v_verify import configure_p2v_dependencies
            from server.flows.worker_bootstrap import _session_factory as _sf2, _storage as _st2
            groq_key = x_groq_key or os.environ.get("GROQ_API_KEY", "")
            configure_p2v_dependencies(
                session_factory=_sf2,
                storage=_st2,
                whisperx_url=os.environ.get("WHISPERX_URL", "http://localhost:7860"),
                groq_api_key=groq_key or None,
                groq_proxy=os.environ.get("HTTPS_PROXY"),
            )

        async def _retry_dev():
            import logging
            from server.flows.worker_bootstrap import _session_factory
            _log = logging.getLogger("dev_retry")
            try:
                STAGE_ORDER = ["p2", "p2c", "p2v", "p5"]
                start_idx = STAGE_ORDER.index(from_stage) if from_stage in STAGE_ORDER else 0
                stages_to_run = STAGE_ORDER[start_idx:] if cascade else [from_stage]

                async def _mark(stage: str, status: str, error: str | None = None, started: datetime | None = None, context: dict | None = None):
                    from server.core.repositories import StageRunRepo, EventRepo
                    async with _session_factory() as s:
                        sr_repo = StageRunRepo(s)
                        existing = await sr_repo.get(chunk_id, stage)
                        attempt = (existing.attempt + 1) if existing and status == "running" else (existing.attempt if existing else 1)
                        finished = datetime.now(timezone.utc) if status in ("ok", "failed") else None
                        duration_ms = int((finished - started).total_seconds() * 1000) if finished and started else None
                        await sr_repo.upsert(chunk_id=chunk_id, stage=stage, status=status, attempt=attempt,
                            started_at=started, finished_at=finished, duration_ms=duration_ms, error=error)
                        if context and status in ("ok", "failed"):
                            await EventRepo(s).write(episode_id=episode_id, chunk_id=chunk_id,
                                kind=f"stage_{status}", payload={"stage": stage, "attempt": attempt, "durationMs": duration_ms, **context})
                        await s.commit()

                # Read chunk text + config
                async with _session_factory() as s:
                    from server.core.repositories import ChunkRepo, EpisodeRepo
                    _chunk = await ChunkRepo(s).get(chunk_id)
                    _text = _chunk.text_normalized if _chunk else ""
                    ep = await EpisodeRepo(s).get(episode_id)
                    tts_config = (ep.config if ep else None) or {}

                for stage in stages_to_run:
                    t0 = datetime.now(timezone.utc)
                    await _mark(stage, "running", started=t0)
                    try:
                        if stage == "p2":
                            from server.flows.tasks.p2_synth import run_p2_synth
                            result = await run_p2_synth(chunk_id, params=tts_config or None)
                            await _mark(stage, "ok", started=t0, context={
                                "request": {"text": _text[:100], **(tts_config if isinstance(tts_config, dict) else {})},
                                "response": {"takeId": result.take_id, "audioUri": result.audio_uri, "durationS": result.duration_s},
                            })
                        elif stage == "p2c":
                            from server.flows.tasks.p2c_check import run_p2c_check
                            result = await run_p2c_check(chunk_id)
                            await _mark(stage, "ok", started=t0, context={
                                "response": result if isinstance(result, dict) else {"status": "ok"},
                            })
                        elif stage == "p2v":
                            from server.flows.tasks.p2v_verify import run_p2v_verify
                            result = await run_p2v_verify(chunk_id)
                            await _mark(stage, "ok", started=t0, context={
                                "response": {"verdict": result.verdict, "charRatio": result.char_ratio, "transcriptUri": result.transcript_uri},
                            })
                        elif stage == "p3":
                            # Legacy fallback — map to p2v
                            from server.flows.tasks.p2v_verify import run_p2v_verify
                            result = await run_p2v_verify(chunk_id)
                            await _mark("p2v", "ok", started=t0, context={
                                "response": {"verdict": result.verdict, "charRatio": result.char_ratio},
                            })
                        elif stage == "p5":
                            from server.flows.tasks.p5_subtitles import run_p5_subtitles
                            result = await run_p5_subtitles(chunk_id)
                            await _mark(stage, "ok", started=t0, context={
                                "response": {"subtitleUri": result.subtitle_uri, "lineCount": result.line_count},
                            })
                        _log.info("retry %s %s → ok", chunk_id, stage)
                    except Exception as e:
                        err_msg = f"{type(e).__name__}: {e}" if str(e).strip() else type(e).__name__
                        await _mark(stage, "failed", error=err_msg, started=t0)
                        _log.error("retry %s %s → failed: %s", chunk_id, stage, err_msg)
                        break
            except Exception as exc:
                import logging
                logging.getLogger("dev_retry").error("retry failed: %s", exc, exc_info=True)

        asyncio.create_task(_retry_dev())

    await session.commit()
    return RetryResponse(flow_run_id=flow_run_id)


# ---------------------------------------------------------------------------
# POST /episodes/{id}/chunks/{cid}/finalize-take
# ---------------------------------------------------------------------------


@router.post(
    "/episodes/{episode_id}/chunks/{chunk_id}/finalize-take",
    response_model=FinalizeResponse,
)
async def finalize_take(
    episode_id: str,
    chunk_id: str,
    take_id: str,
    session: AsyncSession = Depends(get_session),
    prefect_client: Any = Depends(get_prefect_client),
) -> FinalizeResponse:
    chunk_repo = ChunkRepo(session)
    chunk = await chunk_repo.get(chunk_id)
    if chunk is None or chunk.episode_id != episode_id:
        raise DomainError("not_found", f"chunk '{chunk_id}' not found in episode '{episode_id}'")

    take_repo = TakeRepo(session)
    take = await take_repo.select(take_id)
    if take is None or take.chunk_id != chunk_id:
        raise DomainError("not_found", f"take '{take_id}' not found in chunk '{chunk_id}'")

    import asyncio, uuid
    use_prefect = os.environ.get("TTS_USE_PREFECT", "").lower() in ("1", "true", "yes")
    flow_run_id = str(uuid.uuid4())

    if use_prefect:
        flow_run = await prefect_client.create_flow_run_from_deployment(
            "finalize-take/finalize-take",
            parameters={
                "episode_id": episode_id,
                "chunk_id": chunk_id,
                "take_id": take_id,
            },
        )
        flow_run_id = str(flow_run.id)
    else:
        from server.flows.worker_bootstrap import bootstrap as _bootstrap
        _bootstrap()

        async def _finalize_dev():
            try:
                from server.flows.worker_bootstrap import _session_factory
                # Set selected take
                async with _session_factory() as s:
                    await ChunkRepo(s).set_selected_take(chunk_id, take_id)
                    await s.commit()
                # Run P3 → P5
                from server.flows.tasks.p3_transcribe import run_p3_transcribe
                from server.flows.tasks.p5_subtitles import run_p5_subtitles
                await run_p3_transcribe(chunk_id)
                await run_p5_subtitles(chunk_id)
            except Exception as exc:
                import logging
                logging.getLogger("finalize_take").error("finalize failed: %s", exc, exc_info=True)
        asyncio.create_task(_finalize_dev())

    await session.commit()
    return FinalizeResponse(flow_run_id=flow_run_id)


# ---------------------------------------------------------------------------
# POST /episodes/{id}/duplicate
# ---------------------------------------------------------------------------


@router.post(
    "/episodes/{episode_id}/duplicate",
    response_model=EpisodeView,
    status_code=201,
)
async def duplicate_episode(
    episode_id: str,
    body: DuplicateRequest,
    session: AsyncSession = Depends(get_session),
    storage: MinIOStorage = Depends(get_storage),
) -> EpisodeView:
    repo = EpisodeRepo(session)
    original = await repo.get(episode_id)
    if original is None:
        raise DomainError("not_found", f"episode '{episode_id}' not found")

    # Check new_id is not taken
    existing = await repo.get(body.new_id)
    if existing is not None:
        raise DomainError("invalid_input", f"episode '{body.new_id}' already exists")

    # Read original script from MinIO
    script_key = episode_script_key(episode_id)
    try:
        script_bytes = await storage.download_bytes(script_key)
    except Exception:
        raise DomainError("not_found", f"script for episode '{episode_id}' not found in storage")

    # Upload script under new id
    new_key = episode_script_key(body.new_id)
    script_uri = await storage.upload_bytes(new_key, script_bytes, "application/json")

    payload = EpisodeCreate(
        id=body.new_id,
        title=original.title,
        description=original.description,
        script_uri=script_uri,
        config=original.config or {},
    )
    ep = await repo.create(payload)

    event_repo = EventRepo(session)
    await event_repo.write(
        episode_id=ep.id,
        chunk_id=None,
        kind="episode_created",
        payload={"title": ep.title, "duplicated_from": episode_id},
    )

    await session.commit()
    return EpisodeView.model_validate(ep)


# ---------------------------------------------------------------------------
# POST /episodes/{id}/archive
# ---------------------------------------------------------------------------


@router.post("/episodes/{episode_id}/archive", response_model=ArchiveResponse)
async def archive_episode(
    episode_id: str,
    session: AsyncSession = Depends(get_session),
) -> ArchiveResponse:
    repo = EpisodeRepo(session)
    ep = await repo.get(episode_id)
    if ep is None:
        raise DomainError("not_found", f"episode '{episode_id}' not found")

    archived = await repo.archive(episode_id)
    if not archived:
        raise DomainError("not_found", f"episode '{episode_id}' not found")

    await session.commit()

    # Re-fetch to get the archived_at timestamp
    ep = await repo.get(episode_id)
    return ArchiveResponse(archived_at=ep.archived_at)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# POST /episodes/{id}/lock | /episodes/{id}/unlock
# ---------------------------------------------------------------------------


@router.post("/episodes/{episode_id}/lock", response_model=LockResponse)
async def lock_episode(
    episode_id: str,
    session: AsyncSession = Depends(get_session),
) -> LockResponse:
    repo = EpisodeRepo(session)
    ep = await repo.get(episode_id)
    if ep is None:
        raise DomainError("not_found", f"episode '{episode_id}' not found")
    await repo.set_locked(episode_id, True)
    await session.commit()
    return LockResponse(locked=True)


@router.post("/episodes/{episode_id}/unlock", response_model=LockResponse)
async def unlock_episode(
    episode_id: str,
    session: AsyncSession = Depends(get_session),
) -> LockResponse:
    repo = EpisodeRepo(session)
    ep = await repo.get(episode_id)
    if ep is None:
        raise DomainError("not_found", f"episode '{episode_id}' not found")
    await repo.set_locked(episode_id, False)
    await session.commit()
    return LockResponse(locked=False)


# ---------------------------------------------------------------------------
# POST /episodes/{id}/cancel
# ---------------------------------------------------------------------------


class CancelResponse(_CamelBase):
    cancelled: bool


@router.post("/episodes/{episode_id}/cancel", response_model=CancelResponse)
async def cancel_episode(
    episode_id: str,
    session: AsyncSession = Depends(get_session),
) -> CancelResponse:
    """Cancel a running episode pipeline."""
    repo = EpisodeRepo(session)
    ep = await repo.get(episode_id)
    if ep is None:
        raise DomainError("not_found", f"episode '{episode_id}' not found")
    if ep.status != "running":
        raise DomainError("invalid_state", "episode is not running")

    task = _running_tasks.get(episode_id)
    if task and not task.done():
        task.cancel()

    await repo.set_status(episode_id, "ready")
    await session.commit()
    return CancelResponse(cancelled=True)


# ---------------------------------------------------------------------------
# GET /episodes/{id}/chunks/{cid}/log
# ---------------------------------------------------------------------------


@router.get(
    "/episodes/{episode_id}/chunks/{chunk_id}/log",
    response_model=ChunkLogResponse,
)
async def get_chunk_log(
    episode_id: str,
    chunk_id: str,
    stage: str = Query(..., description="Stage name, e.g. p2"),
    session: AsyncSession = Depends(get_session),
    storage: MinIOStorage = Depends(get_storage),
) -> ChunkLogResponse:
    # Verify chunk belongs to episode
    chunk_repo = ChunkRepo(session)
    chunk = await chunk_repo.get(chunk_id)
    if chunk is None or chunk.episode_id != episode_id:
        raise DomainError("not_found", f"chunk '{chunk_id}' not found in episode '{episode_id}'")

    # Get stage run for the log_uri
    sr_repo = StageRunRepo(session)
    sr = await sr_repo.get(chunk_id, stage)
    if sr is None or not sr.log_uri:
        raise DomainError("not_found", f"no log found for chunk '{chunk_id}' stage '{stage}'")

    # log_uri is s3://bucket/key — extract key (strip "s3://bucket/" prefix)
    if sr.log_uri.startswith("s3://"):
        # s3://bucket/path/to/file → path/to/file
        parts = sr.log_uri.split("/", 3)  # ['s3:', '', 'bucket', 'path/to/file']
        log_key = parts[3] if len(parts) > 3 else ""
    else:
        log_key = sr.log_uri

    try:
        log_bytes = await storage.download_bytes(log_key)
    except (S3Error, Exception):
        raise DomainError("not_found", f"log file not found in storage for chunk '{chunk_id}' stage '{stage}'")

    return ChunkLogResponse(
        content=log_bytes.decode("utf-8", errors="replace"),
        stage=stage,
        chunk_id=chunk_id,
    )


# ---------------------------------------------------------------------------
# GET /episodes/{id}/chunks/{cid}/stage-context?stage=p2
# ---------------------------------------------------------------------------


@router.get("/episodes/{episode_id}/chunks/{chunk_id}/stage-context")
async def get_stage_context(
    episode_id: str,
    chunk_id: str,
    stage: str = Query(...),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Return the latest execution context (request/response params) for a stage.

    Reads from events table — the stage_ok/stage_failed event payload
    written by dev runner with request/response context.
    """
    event_repo = EventRepo(session)
    events = await event_repo.list_recent(episode_id, limit=50)
    # Find the most recent stage_ok or stage_failed for this chunk+stage
    for ev in reversed(events):
        if ev.chunk_id == chunk_id and ev.payload.get("stage") == stage:
            if ev.kind in ("stage_ok", "stage_failed"):
                return {"found": True, "kind": ev.kind, "payload": ev.payload, "createdAt": str(ev.created_at)}
    return {"found": False}


# ---------------------------------------------------------------------------
# GET /episodes/{id}/logs
# ---------------------------------------------------------------------------


@router.get("/episodes/{episode_id}/logs", response_model=EpisodeLogsResponse)
async def get_episode_logs(
    episode_id: str,
    tail: int = Query(100, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
) -> EpisodeLogsResponse:
    repo = EpisodeRepo(session)
    ep = await repo.get(episode_id)
    if ep is None:
        raise DomainError("not_found", f"episode '{episode_id}' not found")

    event_repo = EventRepo(session)
    events = await event_repo.list_recent(episode_id, limit=tail)

    lines: list[str] = []
    for ev in events:
        ts = ev.created_at.strftime("%Y-%m-%d %H:%M:%S") if ev.created_at else "?"
        chunk_part = f" chunk={ev.chunk_id}" if ev.chunk_id else ""
        payload_str = " ".join(f"{k}={v}" for k, v in (ev.payload or {}).items())
        lines.append(f"[{ts}]{chunk_part} {ev.kind} {payload_str}".rstrip())

    return EpisodeLogsResponse(lines=lines)


# ---------------------------------------------------------------------------
# GET /episodes/{id}/script — preview or download the original script.json
# ---------------------------------------------------------------------------


@router.get("/episodes/{episode_id}/script")
async def get_episode_script(
    episode_id: str,
    session: AsyncSession = Depends(get_session),
    storage: MinIOStorage = Depends(get_storage),
):
    """Return the original script.json for this episode."""
    repo = EpisodeRepo(session)
    ep = await repo.get(episode_id)
    if ep is None:
        raise DomainError("not_found", f"episode '{episode_id}' not found")

    key = episode_script_key(episode_id)
    try:
        data = await storage.download_bytes(key)
    except Exception:
        raise DomainError("not_found", f"script not found for episode '{episode_id}'")

    import json as _json
    return _json.loads(data)


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Export — async background export with SSE progress
# ---------------------------------------------------------------------------

# Track running export tasks (dev mode only; production uses Prefect)
_export_tasks: dict[str, asyncio.Task] = {}


@router.post("/episodes/{episode_id}/export")
async def trigger_export(
    episode_id: str,
    session: AsyncSession = Depends(get_session),
    storage: MinIOStorage = Depends(get_storage),
):
    """Trigger async export. Returns immediately with status.

    The export runs in the background and emits SSE events:
    export_started → export_finished (with zip_key) / export_failed.
    """
    from server.core.export_logic import export_zip_key, run_export

    repo = EpisodeRepo(session)
    ep = await repo.get(episode_id)
    if ep is None:
        raise DomainError("not_found", f"episode '{episode_id}' not found")

    # Prevent duplicate exports
    if episode_id in _export_tasks and not _export_tasks[episode_id].done():
        return {"status": "running", "message": "export already in progress"}

    from server.core.db import get_sessionmaker
    session_factory = get_sessionmaker()

    async def _run():
        try:
            await run_export(episode_id, session_factory=session_factory, storage=storage)
        except Exception:
            log.exception("Export failed for %s", episode_id)

    task = asyncio.create_task(_run())
    _export_tasks[episode_id] = task
    task.add_done_callback(lambda _: _export_tasks.pop(episode_id, None))

    return {"status": "started", "message": "export triggered"}


@router.get("/episodes/{episode_id}/export/status")
async def export_status(
    episode_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Check export status by querying the latest export event."""
    from server.core.export_logic import export_zip_key

    # Check latest export event
    stmt = (
        select(Event)
        .where(Event.episode_id == episode_id, Event.kind.in_(["export_started", "export_finished", "export_failed"]))
        .order_by(Event.id.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    event = result.scalar_one_or_none()

    if event is None:
        return {"status": "none"}
    if event.kind == "export_started":
        return {"status": "running"}
    if event.kind == "export_finished":
        return {
            "status": "done",
            "zip_key": event.payload.get("zip_key"),
            "size_bytes": event.payload.get("size_bytes"),
        }
    # export_failed
    return {"status": "failed", "error": event.payload.get("error", "unknown")}


@router.get("/episodes/{episode_id}/export/download")
async def download_export(
    episode_id: str,
    storage: MinIOStorage = Depends(get_storage),
):
    """Download the exported zip from MinIO."""
    from urllib.parse import quote

    from fastapi.responses import StreamingResponse

    from server.core.export_logic import export_zip_key

    zip_key = export_zip_key(episode_id)
    if not await storage.exists(zip_key):
        raise DomainError("not_found", "export not found — trigger export first")

    zip_bytes = await storage.download_bytes(zip_key)
    safe_filename = quote(f"{episode_id}.zip")
    return StreamingResponse(
        iter([zip_bytes]),
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{safe_filename}",
            "Content-Length": str(len(zip_bytes)),
        },
    )
