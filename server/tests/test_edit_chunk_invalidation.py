"""Coverage for ``POST /episodes/{id}/chunks/{cid}/edit`` invalidation semantics.

Purpose
-------

Today the route only delegates to ``ChunkRepo.apply_edits`` which mutates
``text_normalized`` / ``subtitle_text`` / ``extra_metadata`` and stamps
``last_edited_at``. It does **not** reset ``chunk.status``, does not clear
``selected_take_id``, and does not delete or mark stale the existing takes
or the ``p2v`` (transcript) stage run.

If a user edits a chunk but does not immediately cascade-retry the whole
pipeline, the DB is left with:

  * ``status = synth_done`` / ``verified`` (pointing to stale audio)
  * ``selected_take_id`` still pointing at the *old* audio
  * ``stage_runs`` for ``p2`` / ``p2v`` still marked ``ok`` (stale transcript)

The "current behaviour" tests below lock that down so a regression is
detectable. The "expected behaviour" tests are marked ``xfail`` with a
concrete bug reason — when the invalidation is added in the route, those
xfails flip to pass and we remove the markers.

This file strictly **adds tests**. It does not import or modify any
business code.
"""

from __future__ import annotations

import io
import json
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from sqlalchemy import select

from server.core.domain import ChunkInput, TakeAppend
from server.core.models import Base, Take
from server.core.repositories import ChunkRepo, StageRunRepo, TakeRepo


# ---------------------------------------------------------------------------
# Isolated TestClient wiring (does not share globals with tests/api).
# ---------------------------------------------------------------------------


_engine = None
_maker: Any = None


async def _override_get_session() -> AsyncIterator[AsyncSession]:
    async with _maker() as session:  # type: ignore[misc]
        yield session


def _override_get_storage() -> Any:
    storage = MagicMock()
    storage.upload_bytes = AsyncMock(return_value="s3://tts-harness/test/script.json")
    storage.ensure_bucket = AsyncMock()
    return storage


async def _override_get_prefect_client() -> AsyncIterator[Any]:
    client = AsyncMock()
    flow_run = MagicMock()
    flow_run.id = uuid4()
    client.create_flow_run_from_deployment = AsyncMock(return_value=flow_run)
    yield client


@pytest_asyncio.fixture()
async def client() -> AsyncIterator[AsyncClient]:
    global _engine, _maker
    _engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    _maker = async_sessionmaker(_engine, expire_on_commit=False)

    from server.api.main import app
    from server.api.deps import get_session, get_storage, get_prefect_client

    app.dependency_overrides[get_session] = _override_get_session
    app.dependency_overrides[get_storage] = _override_get_storage
    app.dependency_overrides[get_prefect_client] = _override_get_prefect_client

    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    await _engine.dispose()


@pytest_asyncio.fixture()
async def verified_chunk(client: AsyncClient) -> AsyncClient:
    """Seed a chunk that has gone through P2 + P2v — i.e. the exact state
    where a follow-up edit should invalidate downstream artefacts."""
    # Create episode via API so event stream / episode row is realistic.
    script = json.dumps({"title": "Inv", "segments": [{"id": 1, "text": "hi"}]})
    resp = await client.post(
        "/episodes",
        data={"id": "ep-inv", "title": "Invalidation Episode"},
        files={"script": ("script.json", io.BytesIO(script.encode()), "application/json")},
    )
    assert resp.status_code == 201

    # Seed chunk + take + p2/p2v stage_runs in a realistic "verified" state.
    async with _maker() as session:  # type: ignore[misc]
        chunk_repo = ChunkRepo(session)
        await chunk_repo.bulk_insert(
            [
                ChunkInput(
                    id="ep-inv:shot01:0",
                    episode_id="ep-inv",
                    shot_id="shot01",
                    idx=0,
                    text="original text",
                    text_normalized="original text",
                    char_count=13,
                ),
            ]
        )
        # Simulate P2 having appended a take.
        take_repo = TakeRepo(session)
        await take_repo.append(
            TakeAppend(
                id="take-orig",
                chunk_id="ep-inv:shot01:0",
                audio_uri="s3://tts/original.wav",
                duration_s=1.25,
            )
        )
        # Chunk points at that take, status advanced to verified (post-P2v).
        await chunk_repo.set_selected_take("ep-inv:shot01:0", "take-orig")
        await chunk_repo.set_status("ep-inv:shot01:0", "verified")

        # Simulate a successful P2 and P2v stage_run, including a transcript
        # payload persisted on the chunk's extra_metadata (current shape used
        # by P2v verifier — the actual field name varies across branches, so
        # we store it under a vendor-neutral key that all readers use).
        sr_repo = StageRunRepo(session)
        await sr_repo.upsert(chunk_id="ep-inv:shot01:0", stage="p2", status="ok")
        await sr_repo.upsert(chunk_id="ep-inv:shot01:0", stage="p2v", status="ok")

        # Stash a fake transcript into chunk metadata, mimicking what P2v
        # writes. We read this back post-edit to prove it is *not* cleared.
        chunk = await chunk_repo.get("ep-inv:shot01:0")
        assert chunk is not None
        new_meta = dict(chunk.extra_metadata or {})
        new_meta["transcript"] = {
            "text": "original text",
            "take_id": "take-orig",
            "score": 1.0,
        }
        chunk.extra_metadata = new_meta

        await session.commit()

    return client


# ---------------------------------------------------------------------------
# Current-behaviour tests — lock in today's semantics so a regression is loud.
# ---------------------------------------------------------------------------


class TestEditChunkCurrentBehaviour:
    """Document what edit_chunk does today. Green under current code."""

    async def test_text_normalized_is_updated(self, verified_chunk: AsyncClient):
        resp = await verified_chunk.post(
            "/episodes/ep-inv/chunks/ep-inv:shot01:0/edit",
            params={"text_normalized": "rewritten text"},
        )
        assert resp.status_code == 200
        assert resp.json()["updated"] == 1

        async with _maker() as session:  # type: ignore[misc]
            chunk = await ChunkRepo(session).get("ep-inv:shot01:0")
            assert chunk is not None
            assert chunk.text_normalized == "rewritten text"
            # char_count is recomputed from the new text.
            assert chunk.char_count == len("rewritten text")
            assert chunk.last_edited_at is not None

    async def test_status_is_not_reset_today(self, verified_chunk: AsyncClient):
        """edit_chunk currently leaves chunk.status untouched.

        If this test starts *failing* it means someone added invalidation
        logic — great news, but the matching xfail below must be unxfailed
        at the same time.
        """
        resp = await verified_chunk.post(
            "/episodes/ep-inv/chunks/ep-inv:shot01:0/edit",
            params={"text_normalized": "rewritten text"},
        )
        assert resp.status_code == 200

        async with _maker() as session:  # type: ignore[misc]
            chunk = await ChunkRepo(session).get("ep-inv:shot01:0")
            assert chunk is not None
            assert chunk.status == "verified"

    async def test_selected_take_is_not_cleared_today(
        self, verified_chunk: AsyncClient
    ):
        resp = await verified_chunk.post(
            "/episodes/ep-inv/chunks/ep-inv:shot01:0/edit",
            params={"text_normalized": "rewritten text"},
        )
        assert resp.status_code == 200

        async with _maker() as session:  # type: ignore[misc]
            chunk = await ChunkRepo(session).get("ep-inv:shot01:0")
            assert chunk is not None
            # Still points at the stale take produced before the edit.
            assert chunk.selected_take_id == "take-orig"

    async def test_takes_and_transcript_survive_edit_today(
        self, verified_chunk: AsyncClient
    ):
        resp = await verified_chunk.post(
            "/episodes/ep-inv/chunks/ep-inv:shot01:0/edit",
            params={"text_normalized": "rewritten text"},
        )
        assert resp.status_code == 200

        async with _maker() as session:  # type: ignore[misc]
            chunk_repo = ChunkRepo(session)
            sr_repo = StageRunRepo(session)

            # Take row still there.
            chunk = await chunk_repo.get("ep-inv:shot01:0")
            assert chunk is not None
            takes_res = await session.execute(
                select(Take).where(Take.chunk_id == "ep-inv:shot01:0")
            )
            takes = list(takes_res.scalars())
            assert len(takes) == 1
            assert takes[0].id == "take-orig"

            # Transcript payload still in metadata — this is the stale data
            # that could mismatch the new text on a subsequent P2v-only run.
            assert chunk.extra_metadata.get("transcript", {}).get("text") == "original text"

            # p2 / p2v stage_runs still marked ``ok`` — nothing is stale.
            sr_p2 = await sr_repo.get("ep-inv:shot01:0", "p2")
            sr_p2v = await sr_repo.get("ep-inv:shot01:0", "p2v")
            assert sr_p2 is not None
            assert sr_p2v is not None
            assert sr_p2.status == "ok"
            assert sr_p2v.status == "ok"
            assert sr_p2.stale is False
            assert sr_p2v.stale is False


# ---------------------------------------------------------------------------
# Expected-behaviour tests — xfail today, pass after the bug is fixed.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    reason=(
        "bug: edit_chunk does not invalidate stale take/transcript. "
        "Editing text_normalized should at minimum reset chunk.status back to "
        "'pending' (or equivalent) so the user is forced to re-run P2 before "
        "the chunk can be considered verified again."
    ),
    strict=True,
)
async def test_status_should_revert_to_pending_after_edit(
    verified_chunk: AsyncClient,
):
    resp = await verified_chunk.post(
        "/episodes/ep-inv/chunks/ep-inv:shot01:0/edit",
        params={"text_normalized": "rewritten text"},
    )
    assert resp.status_code == 200

    async with _maker() as session:  # type: ignore[misc]
        chunk = await ChunkRepo(session).get("ep-inv:shot01:0")
        assert chunk is not None
        # After edit, the audio + transcript no longer match the text, so the
        # chunk must not still be considered ``verified``.
        assert chunk.status == "pending"


@pytest.mark.xfail(
    reason=(
        "bug: edit_chunk does not mark the p2v stage_run stale. "
        "The existing transcript was computed against the OLD text, so it is "
        "no longer trustworthy; downstream consumers (p5/p6 or a manual p2v "
        "re-run) need a signal that this row must be re-computed."
    ),
    strict=True,
)
async def test_p2v_stage_run_should_be_marked_stale_after_edit(
    verified_chunk: AsyncClient,
):
    resp = await verified_chunk.post(
        "/episodes/ep-inv/chunks/ep-inv:shot01:0/edit",
        params={"text_normalized": "rewritten text"},
    )
    assert resp.status_code == 200

    async with _maker() as session:  # type: ignore[misc]
        sr_repo = StageRunRepo(session)
        sr_p2v = await sr_repo.get("ep-inv:shot01:0", "p2v")
        assert sr_p2v is not None
        # Either stale=True or status flipped out of "ok" is acceptable — both
        # encode "don't trust this without a re-run". Current code does
        # neither, so this xfails.
        assert sr_p2v.stale is True or sr_p2v.status != "ok"
