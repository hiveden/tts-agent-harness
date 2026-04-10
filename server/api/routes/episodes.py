"""Episode + chunk routes.

All business logic is delegated to repositories. Route handlers are thin:
validate input → call repo → return response model.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from minio.error import S3Error
from pydantic import BaseModel
from server.core.domain import _CamelBase
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
    chunk_details: list[ChunkDetail] = []
    for c in chunks:
        takes = await take_repo.list_by_chunk(c.id)
        stage_runs = await sr_repo.list_by_chunk(c.id)
        # Build from dict to avoid lazy-load issues on ORM relationships
        chunk_dict = {
            "id": c.id,
            "episode_id": c.episode_id,
            "shot_id": c.shot_id,
            "idx": c.idx,
            "text": c.text,
            "text_normalized": c.text_normalized,
            "subtitle_text": c.subtitle_text,
            "status": c.status,
            "selected_take_id": c.selected_take_id,
            "boundary_hash": c.boundary_hash,
            "char_count": c.char_count,
            "last_edited_at": c.last_edited_at,
            "extra_metadata": c.extra_metadata,
            "takes": [TakeView.model_validate(t) for t in takes],
            "stage_runs": [StageRunView.model_validate(sr) for sr in stage_runs],
        }
        chunk_details.append(ChunkDetail(**chunk_dict))

    # Build from dict to avoid lazy-load on Episode.chunks relationship
    ep_dict = {
        "id": ep.id,
        "title": ep.title,
        "description": ep.description,
        "status": ep.status,
        "script_uri": ep.script_uri,
        "config": ep.config,
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
    mode = (body.mode if body else None) or "synthesize"
    chunk_ids = body.chunk_ids if body else None

    repo = EpisodeRepo(session)
    ep = await repo.get(episode_id)
    if ep is None:
        raise DomainError("not_found", f"episode '{episode_id}' not found")

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
        from server.flows.run_episode import run_episode_flow
        from server.flows.worker_bootstrap import bootstrap as _bootstrap

        async def _run_in_background():
            try:
                _bootstrap()  # idempotent — sets up DB/MinIO/task DI
                await run_episode_flow(
                    episode_id=episode_id,
                    mode=mode,
                    chunk_ids=chunk_ids,
                )
            except Exception as exc:
                import logging
                logging.getLogger("run_episode").error("flow failed: %s", exc, exc_info=True)

        asyncio.create_task(_run_in_background())

    await repo.set_status(episode_id, "running")

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
    from_stage: str = "p2",
    cascade: bool = True,
    session: AsyncSession = Depends(get_session),
    prefect_client: Any = Depends(get_prefect_client),
) -> RetryResponse:
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
        from server.flows.retry_chunk import retry_chunk_stage_flow
        from server.flows.worker_bootstrap import bootstrap as _bootstrap
        async def _retry_bg():
            try:
                _bootstrap()
                await retry_chunk_stage_flow(episode_id, chunk_id, from_stage, cascade=cascade)
            except Exception as exc:
                import logging
                logging.getLogger("retry_chunk").error("retry failed: %s", exc, exc_info=True)
        asyncio.create_task(_retry_bg())

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
        from server.flows.finalize_take import finalize_take_flow
        from server.flows.worker_bootstrap import bootstrap as _bootstrap
        async def _finalize_bg():
            try:
                _bootstrap()
                await finalize_take_flow(episode_id, chunk_id, take_id)
            except Exception as exc:
                import logging
                logging.getLogger("finalize_take").error("finalize failed: %s", exc, exc_info=True)
        asyncio.create_task(_finalize_bg())

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
