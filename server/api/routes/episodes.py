"""Episode + chunk routes.

All business logic is delegated to repositories. Route handlers are thin:
validate input → call repo → return response model.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel
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


class RunResponse(BaseModel):
    flow_run_id: str


class RetryResponse(BaseModel):
    flow_run_id: str


class FinalizeResponse(BaseModel):
    flow_run_id: str


class EditResponse(BaseModel):
    updated: int


class DeleteResponse(BaseModel):
    deleted: bool


# ---------------------------------------------------------------------------
# GET /episodes
# ---------------------------------------------------------------------------


@router.get("/episodes", response_model=list[EpisodeSummary])
async def list_episodes(
    session: AsyncSession = Depends(get_session),
) -> list[EpisodeSummary]:
    repo = EpisodeRepo(session)
    chunk_repo = ChunkRepo(session)
    episodes = await repo.list()
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
    session: AsyncSession = Depends(get_session),
    prefect_client: Any = Depends(get_prefect_client),
) -> RunResponse:
    repo = EpisodeRepo(session)
    ep = await repo.get(episode_id)
    if ep is None:
        raise DomainError("not_found", f"episode '{episode_id}' not found")

    flow_run = await prefect_client.create_flow_run_from_deployment(
        "run-episode/run-episode",
        parameters={"episode_id": episode_id},
    )

    await repo.set_status(episode_id, "running")

    event_repo = EventRepo(session)
    await event_repo.write(
        episode_id=episode_id,
        chunk_id=None,
        kind="episode_status_changed",
        payload={"status": "running"},
    )
    await session.commit()

    return RunResponse(flow_run_id=str(flow_run.id))


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

    flow_run = await prefect_client.create_flow_run_from_deployment(
        "retry-chunk-stage/retry-chunk-stage",
        parameters={
            "episode_id": episode_id,
            "chunk_id": chunk_id,
            "from_stage": from_stage,
            "cascade": cascade,
        },
    )
    await session.commit()

    return RetryResponse(flow_run_id=str(flow_run.id))


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

    flow_run = await prefect_client.create_flow_run_from_deployment(
        "finalize-take/finalize-take",
        parameters={
            "episode_id": episode_id,
            "chunk_id": chunk_id,
            "take_id": take_id,
        },
    )
    await session.commit()

    return FinalizeResponse(flow_run_id=str(flow_run.id))
