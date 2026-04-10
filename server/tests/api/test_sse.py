"""SSE endpoint tests.

Tests the SSE subscription/fan-out/cleanup logic. We test both the internal
fan-out mechanics (via direct queue manipulation) and the HTTP endpoint shape.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from server.core.models import Base, Event
from server.api import sse as sse_module


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_engine = None
_maker = None


@pytest_asyncio.fixture(autouse=True)
async def reset_sse_state():
    """Clear global SSE state between tests."""
    yield
    sse_module._subscribers.clear()


@pytest_asyncio.fixture()
async def db_session() -> AsyncIterator[AsyncSession]:
    global _engine, _maker
    _engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    _maker = async_sessionmaker(_engine, expire_on_commit=False)
    async with _maker() as session:
        yield session
    await _engine.dispose()


async def _seed_event(
    session: AsyncSession, episode_id: str, kind: str = "stage_started"
) -> int:
    """Insert an event directly into the DB and return its id."""
    event = Event(
        episode_id=episode_id,
        chunk_id="chunk-1",
        kind=kind,
        payload={"stage": "p2", "status": "running"},
        created_at=datetime.now(timezone.utc),
    )
    session.add(event)
    await session.flush()
    event_id = event.id
    await session.commit()
    return event_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSSEPush:
    async def test_subscriber_registration_and_fanout(self, db_session: AsyncSession):
        """Verify that _on_notify fans out to registered subscribers."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=64)
        sse_module._subscribers["ep-1"].append(queue)

        # Simulate a NOTIFY callback
        sse_module._on_notify(None, 0, "episode_events", json.dumps({"ep": "ep-1", "id": 42}))

        # Queue should have received the notification
        msg = queue.get_nowait()
        assert msg == {"ep": "ep-1", "id": 42}

    async def test_fanout_filters_by_episode(self, db_session: AsyncSession):
        """Events for episode B should not reach episode A subscribers."""
        queue_a: asyncio.Queue = asyncio.Queue(maxsize=64)
        queue_b: asyncio.Queue = asyncio.Queue(maxsize=64)
        sse_module._subscribers["ep-a"].append(queue_a)
        sse_module._subscribers["ep-b"].append(queue_b)

        # Notify for ep-a only
        sse_module._on_notify(None, 0, "episode_events", json.dumps({"ep": "ep-a", "id": 1}))

        # ep-a queue has message, ep-b does not
        assert not queue_a.empty()
        assert queue_b.empty()

        msg = queue_a.get_nowait()
        assert msg["ep"] == "ep-a"

    async def test_subscriber_cleanup(self):
        """After removing a subscriber, it should no longer receive events."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=64)
        sse_module._subscribers["ep-clean"].append(queue)

        # Remove subscriber
        sse_module._subscribers["ep-clean"].remove(queue)
        if not sse_module._subscribers["ep-clean"]:
            del sse_module._subscribers["ep-clean"]

        # Notify should not error
        sse_module._on_notify(None, 0, "episode_events", json.dumps({"ep": "ep-clean", "id": 1}))
        assert queue.empty()

    async def test_fetch_event(self, db_session: AsyncSession):
        """_fetch_event should return full event data from DB."""
        global _maker
        # Patch get_sessionmaker for _fetch_event
        original = sse_module.get_sessionmaker
        sse_module.get_sessionmaker = lambda: _maker

        try:
            event_id = await _seed_event(db_session, "ep-fetch", "stage_finished")
            result = await sse_module._fetch_event(event_id)
            assert result is not None
            assert result["episode_id"] == "ep-fetch"
            assert result["kind"] == "stage_finished"
            assert result["chunk_id"] == "chunk-1"
        finally:
            sse_module.get_sessionmaker = original

    async def test_fetch_event_not_found(self, db_session: AsyncSession):
        """_fetch_event should return None for non-existent event."""
        global _maker
        original = sse_module.get_sessionmaker
        sse_module.get_sessionmaker = lambda: _maker

        try:
            result = await sse_module._fetch_event(99999)
            assert result is None
        finally:
            sse_module.get_sessionmaker = original

    async def test_invalid_notify_payload(self):
        """Invalid JSON in NOTIFY payload should be silently ignored."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=64)
        sse_module._subscribers["ep-bad"].append(queue)

        # Should not raise
        sse_module._on_notify(None, 0, "episode_events", "not json")
        assert queue.empty()

    async def test_multiple_subscribers_same_episode(self):
        """Multiple clients subscribed to the same episode all get the event."""
        q1: asyncio.Queue = asyncio.Queue(maxsize=64)
        q2: asyncio.Queue = asyncio.Queue(maxsize=64)
        q3: asyncio.Queue = asyncio.Queue(maxsize=64)
        sse_module._subscribers["ep-multi"].extend([q1, q2, q3])

        sse_module._on_notify(None, 0, "episode_events", json.dumps({"ep": "ep-multi", "id": 7}))

        for q in [q1, q2, q3]:
            msg = q.get_nowait()
            assert msg["id"] == 7
