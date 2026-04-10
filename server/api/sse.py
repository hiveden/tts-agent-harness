"""SSE endpoint — Postgres LISTEN/NOTIFY → Server-Sent Events.

Architecture:
- At app startup (lifespan), a raw asyncpg connection is created and
  ``LISTEN episode_events`` is issued.
- A background ``asyncio.Task`` loops on ``connection.wait_for_notify()``,
  parses the NOTIFY payload ``{"ep": ..., "id": ...}``, and fans out to
  per-client ``asyncio.Queue`` instances keyed by ``episode_id``.
- ``GET /episodes/{id}/stream`` creates a queue, subscribes, and yields
  SSE frames until the client disconnects.
- On client disconnect the queue is removed from the subscriber dict.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from server.core.db import get_sessionmaker
from server.core.models import Event

router = APIRouter()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Subscriber registry (module-level singleton)
# ---------------------------------------------------------------------------

# episode_id → list of asyncio.Queue
_subscribers: dict[str, list[asyncio.Queue[dict[str, Any]]]] = defaultdict(list)
_listener_task: asyncio.Task[None] | None = None
_listener_conn: Any = None  # raw asyncpg connection


# ---------------------------------------------------------------------------
# Lifespan helpers (called from main.py)
# ---------------------------------------------------------------------------


async def start_listener(database_url: str) -> None:
    """Create an asyncpg connection, LISTEN, and start the fan-out task."""
    global _listener_task, _listener_conn

    try:
        import asyncpg  # noqa: F811

        # Strip the sqlalchemy prefix to get a raw asyncpg DSN.
        dsn = database_url.replace("postgresql+asyncpg://", "postgresql://")
        _listener_conn = await asyncpg.connect(dsn)
        await _listener_conn.add_listener("episode_events", _on_notify)
        logger.info("SSE listener started on channel 'episode_events'")
    except Exception:
        logger.warning(
            "Could not start Postgres LISTEN (maybe SQLite or no PG). SSE will not push.",
            exc_info=True,
        )


async def stop_listener() -> None:
    global _listener_conn
    if _listener_conn is not None:
        try:
            await _listener_conn.close()
        except Exception:
            pass
        _listener_conn = None


def _on_notify(
    conn: Any,
    pid: int,
    channel: str,
    payload: str,
) -> None:
    """asyncpg listener callback — runs in the event loop."""
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        logger.warning("Invalid NOTIFY payload: %s", payload)
        return

    ep_id = data.get("ep")
    event_id = data.get("id")
    if not ep_id or event_id is None:
        return

    queues = _subscribers.get(ep_id, [])
    for q in queues:
        try:
            q.put_nowait(data)
        except asyncio.QueueFull:
            pass  # drop if client is too slow


# ---------------------------------------------------------------------------
# Fetch full event from DB
# ---------------------------------------------------------------------------


async def _fetch_event(event_id: int) -> dict[str, Any] | None:
    """Read the full event row by id."""
    maker = get_sessionmaker()
    async with maker() as session:
        from sqlalchemy import select

        stmt = select(Event).where(Event.id == event_id)
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return {
            "id": row.id,
            "episode_id": row.episode_id,
            "chunk_id": row.chunk_id,
            "kind": row.kind,
            "payload": row.payload,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }


# ---------------------------------------------------------------------------
# SSE endpoint
# ---------------------------------------------------------------------------


@router.get("/episodes/{episode_id}/stream", tags=["sse"])
async def episode_stream(episode_id: str, request: Request) -> StreamingResponse:
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
    _subscribers[episode_id].append(queue)

    async def _generate():
        try:
            while True:
                # Check client disconnect
                if await request.is_disconnected():
                    break
                try:
                    notify_data = await asyncio.wait_for(queue.get(), timeout=30.0)
                except asyncio.TimeoutError:
                    # Send keepalive comment
                    yield ": keepalive\n\n"
                    continue

                event_id = notify_data.get("id")
                if event_id is None:
                    continue

                full_event = await _fetch_event(event_id)
                if full_event is None:
                    continue

                data_json = json.dumps(full_event)
                yield f"event: stage_event\ndata: {data_json}\n\n"
        finally:
            # Cleanup on disconnect
            subs = _subscribers.get(episode_id, [])
            if queue in subs:
                subs.remove(queue)
            if not subs:
                _subscribers.pop(episode_id, None)

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
