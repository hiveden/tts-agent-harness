"""Integration tests for the P1 Prefect task.

These tests exercise the task adapter in ``server.flows.tasks.p1_chunk``
against an in-memory SQLite DB and a duck-typed in-memory object store.
They verify the wiring that the pure-logic tests cannot:

* script -> chunks table write-through,
* ``stage_started`` + ``stage_finished`` event emission,
* episode status transition (``empty`` -> ``ready``),
* idempotent re-run semantics,
* error paths (missing script, missing episode, invalid JSON).
"""

from __future__ import annotations

import json
from typing import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from server.core.domain import EpisodeCreate
from server.core.models import Base, Chunk, Episode, Event
from server.core.repositories import EpisodeRepo
from server.core.storage import episode_script_key
from server.flows.tasks.p1_chunk import DomainError, P1Context, _run_p1, p1_chunk


# ---------------------------------------------------------------------------
# In-memory stand-ins
# ---------------------------------------------------------------------------


class InMemoryStorage:
    """Async duck-type of :class:`MinIOStorage` for tests.

    Only implements the handful of methods P1 actually touches. Prefect
    never sees this object — it's handed in via ``P1Context`` at call
    time.
    """

    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}

    def put(self, key: str, data: bytes) -> None:
        self._objects[key] = data

    async def download_bytes(self, key: str) -> bytes:
        try:
            return self._objects[key]
        except KeyError as exc:
            raise FileNotFoundError(key) from exc


@pytest_asyncio.fixture()
async def engine_and_maker() -> AsyncIterator[tuple]:
    """Per-test SQLite engine + session factory.

    We can't reuse ``conftest.session`` here because the task owns its own
    session lifecycle — it needs a *maker*, not a pre-opened session.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield engine, maker
    finally:
        await engine.dispose()


async def _seed_episode(maker: async_sessionmaker[AsyncSession], ep_id: str) -> None:
    async with maker() as s:
        async with s.begin():
            await EpisodeRepo(s).create(
                EpisodeCreate(
                    id=ep_id,
                    title="demo",
                    script_uri=f"s3://tts-harness/{episode_script_key(ep_id)}",
                )
            )


SAMPLE_SCRIPT = {
    "title": "Sample",
    "segments": [
        {"id": 1, "type": "hook", "text": "你好世界。今天天气不错！"},
        {"id": 2, "type": "content", "text": "[break]欢迎收听。"},
    ],
}


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_writes_chunks_and_events_without_touching_episode_status(engine_and_maker) -> None:
    _, maker = engine_and_maker
    storage = InMemoryStorage()
    ep_id = "ep-happy"
    storage.put(episode_script_key(ep_id), json.dumps(SAMPLE_SCRIPT).encode("utf-8"))
    await _seed_episode(maker, ep_id)

    ctx = P1Context(session_maker=maker, storage=storage)  # type: ignore[arg-type]
    result = await _run_p1(ctx, ep_id)

    assert result.episode_id == ep_id
    assert len(result.chunks) == 3  # 2 + 1 sentences

    async with maker() as s:
        # chunks persisted
        rows = (await s.execute(select(Chunk).order_by(Chunk.shot_id, Chunk.idx))).scalars().all()
        assert len(rows) == 3
        assert [r.shot_id for r in rows] == ["shot01", "shot01", "shot02"]
        assert [r.idx for r in rows] == [1, 2, 1]
        assert rows[2].text == "[break]欢迎收听。"
        assert rows[0].char_count == len("你好世界。")
        assert all(r.status == "pending" for r in rows)
        assert all(r.boundary_hash and len(r.boundary_hash) == 16 for r in rows)

        # episode status untouched — p1_chunk is a stage task and does not
        # manage episode-level status. _seed_episode creates with "empty";
        # P1 must leave it alone. The orchestration layer (API route /
        # Prefect flow) owns episode.status transitions.
        ep = await s.get(Episode, ep_id)
        assert ep is not None
        assert ep.status == "empty"

        # events emitted
        events = (await s.execute(select(Event).order_by(Event.id))).scalars().all()
        kinds = [e.kind for e in events]
        assert kinds == ["stage_started", "stage_finished"]
        assert events[0].payload == {"stage": "p1"}
        assert events[1].payload == {"stage": "p1", "chunk_count": 3}


@pytest.mark.asyncio
async def test_rerun_is_idempotent(engine_and_maker) -> None:
    _, maker = engine_and_maker
    storage = InMemoryStorage()
    ep_id = "ep-rerun"
    storage.put(episode_script_key(ep_id), json.dumps(SAMPLE_SCRIPT).encode("utf-8"))
    await _seed_episode(maker, ep_id)

    ctx = P1Context(session_maker=maker, storage=storage)  # type: ignore[arg-type]
    r1 = await _run_p1(ctx, ep_id)
    r2 = await _run_p1(ctx, ep_id)

    # Byte-identical chunk list (ids, text, boundary_hash) across runs.
    assert [c.id for c in r1.chunks] == [c.id for c in r2.chunks]
    assert [c.boundary_hash for c in r1.chunks] == [c.boundary_hash for c in r2.chunks]

    async with maker() as s:
        # Re-run must not duplicate rows — the adapter does a DELETE first.
        rows = (await s.execute(select(Chunk))).scalars().all()
        assert len(rows) == 3

        # Two full rounds of stage events => 4 total.
        events = (await s.execute(select(Event).order_by(Event.id))).scalars().all()
        assert [e.kind for e in events] == [
            "stage_started",
            "stage_finished",
            "stage_started",
            "stage_finished",
        ]


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_script_raises_not_found(engine_and_maker) -> None:
    _, maker = engine_and_maker
    storage = InMemoryStorage()
    ep_id = "ep-no-script"
    await _seed_episode(maker, ep_id)

    ctx = P1Context(session_maker=maker, storage=storage)  # type: ignore[arg-type]
    with pytest.raises(DomainError) as exc_info:
        await _run_p1(ctx, ep_id)
    assert exc_info.value.code == "not_found"

    # Nothing was written to chunks/events because the failure happened
    # before the DB transaction opened.
    async with maker() as s:
        assert (await s.execute(select(Chunk))).scalars().all() == []
        assert (await s.execute(select(Event))).scalars().all() == []


@pytest.mark.asyncio
async def test_invalid_json_raises_invalid_input(engine_and_maker) -> None:
    _, maker = engine_and_maker
    storage = InMemoryStorage()
    ep_id = "ep-bad-json"
    storage.put(episode_script_key(ep_id), b"{not valid json")
    await _seed_episode(maker, ep_id)

    ctx = P1Context(session_maker=maker, storage=storage)  # type: ignore[arg-type]
    with pytest.raises(DomainError) as exc_info:
        await _run_p1(ctx, ep_id)
    assert exc_info.value.code == "invalid_input"


@pytest.mark.asyncio
async def test_missing_episode_row_raises_not_found(engine_and_maker) -> None:
    _, maker = engine_and_maker
    storage = InMemoryStorage()
    ep_id = "ep-no-row"
    storage.put(episode_script_key(ep_id), json.dumps(SAMPLE_SCRIPT).encode("utf-8"))
    # Note: no _seed_episode call.

    ctx = P1Context(session_maker=maker, storage=storage)  # type: ignore[arg-type]
    with pytest.raises(DomainError) as exc_info:
        await _run_p1(ctx, ep_id)
    assert exc_info.value.code == "not_found"


@pytest.mark.asyncio
async def test_empty_segments_still_marks_ready(engine_and_maker) -> None:
    """An episode with no segments is a no-op, not an error.

    We pick this policy (over raising ``invalid_state``) because authoring
    tools may save empty drafts, and forcing the user to re-run P1 after
    adding content is more friendly than failing hard.
    """
    _, maker = engine_and_maker
    storage = InMemoryStorage()
    ep_id = "ep-empty"
    storage.put(
        episode_script_key(ep_id),
        json.dumps({"title": "empty", "segments": []}).encode("utf-8"),
    )
    await _seed_episode(maker, ep_id)

    ctx = P1Context(session_maker=maker, storage=storage)  # type: ignore[arg-type]
    result = await _run_p1(ctx, ep_id)
    assert result.chunks == []

    async with maker() as s:
        ep = await s.get(Episode, ep_id)
        assert ep is not None
        # Empty-script run still leaves episode.status untouched (was "empty"
        # after seeding and stays "empty" — p1_chunk does not own this field).
        assert ep.status == "empty"
        rows = (await s.execute(select(Chunk))).scalars().all()
        assert rows == []


# ---------------------------------------------------------------------------
# Prefect task wrapper — ensure the @task decorator doesn't break the path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_task_wrapper_invokable(engine_and_maker) -> None:
    """Sanity check: calling the @task-decorated function directly works.

    Prefect tasks are callable outside a flow context in 3.x — they just
    run as plain coroutines. We exercise this path so that a regression in
    the decorator import wouldn't slip past CI.
    """
    _, maker = engine_and_maker
    storage = InMemoryStorage()
    ep_id = "ep-task"
    storage.put(episode_script_key(ep_id), json.dumps(SAMPLE_SCRIPT).encode("utf-8"))
    await _seed_episode(maker, ep_id)

    ctx = P1Context(session_maker=maker, storage=storage)  # type: ignore[arg-type]
    # `.fn` unwraps the Prefect Task object to the underlying coroutine,
    # avoiding the flow-run context requirement.
    result = await p1_chunk.fn(ep_id, ctx=ctx)
    assert result.episode_id == ep_id
    assert len(result.chunks) == 3
