"""Async repositories over the business schema.

Every repository takes an ``AsyncSession`` in its constructor and never owns
the transaction lifecycle — the caller decides when to commit or roll back.
This lets higher layers (API route handlers, Prefect tasks) compose multiple
repository calls in a single unit of work.

The only module that talks SQL by hand is ``events.py`` (for ``pg_notify``);
everything else goes through SQLAlchemy ORM or ``select()``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from . import events as events_module
from .domain import (
    ChunkEdit,
    ChunkInput,
    EpisodeCreate,
    TakeAppend,
)
from .models import Chunk, Episode, Event, StageRun, Take


# ---------------------------------------------------------------------------
# Episodes
# ---------------------------------------------------------------------------


class EpisodeRepo:
    """CRUD + list/archive/status transitions for episodes."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, payload: EpisodeCreate) -> Episode:
        ep = Episode(
            id=payload.id,
            title=payload.title,
            description=payload.description,
            status="empty",
            script_uri=payload.script_uri,
            config=payload.config,
            extra_metadata=payload.metadata,
        )
        self.session.add(ep)
        await self.session.flush()
        return ep

    async def get(self, episode_id: str) -> Episode | None:
        return await self.session.get(Episode, episode_id)

    async def list(
        self,
        *,
        include_archived: bool = False,
        limit: int | None = None,
    ) -> Sequence[Episode]:
        stmt = select(Episode).order_by(Episode.created_at.desc())
        if not include_archived:
            stmt = stmt.where(Episode.archived_at.is_(None))
        if limit is not None:
            stmt = stmt.limit(limit)
        res = await self.session.execute(stmt)
        return res.scalars().all()

    async def delete(self, episode_id: str) -> bool:
        ep = await self.get(episode_id)
        if ep is None:
            return False
        await self.session.delete(ep)
        await self.session.flush()
        return True

    async def archive(self, episode_id: str) -> bool:
        stmt = (
            update(Episode)
            .where(Episode.id == episode_id)
            .values(archived_at=datetime.now(timezone.utc))
        )
        res = await self.session.execute(stmt)
        return (res.rowcount or 0) > 0

    async def set_status(self, episode_id: str, status: str) -> bool:
        stmt = (
            update(Episode)
            .where(Episode.id == episode_id)
            .values(status=status, updated_at=datetime.now(timezone.utc))
        )
        res = await self.session.execute(stmt)
        return (res.rowcount or 0) > 0

    async def set_locked(self, episode_id: str, locked: bool) -> bool:
        stmt = (
            update(Episode)
            .where(Episode.id == episode_id)
            .values(locked=locked, updated_at=datetime.now(timezone.utc))
        )
        res = await self.session.execute(stmt)
        return (res.rowcount or 0) > 0

    async def list_unlocked_oldest_first(self) -> Sequence[Episode]:
        stmt = (
            select(Episode)
            .where(Episode.locked.is_(False), Episode.archived_at.is_(None))
            .order_by(Episode.updated_at.asc())
        )
        res = await self.session.execute(stmt)
        return res.scalars().all()


# ---------------------------------------------------------------------------
# Chunks
# ---------------------------------------------------------------------------


class ChunkRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, chunk_id: str) -> Chunk | None:
        return await self.session.get(Chunk, chunk_id)

    async def list_by_episode(self, episode_id: str) -> Sequence[Chunk]:
        stmt = (
            select(Chunk)
            .where(Chunk.episode_id == episode_id)
            .order_by(Chunk.shot_id, Chunk.idx)
        )
        res = await self.session.execute(stmt)
        return res.scalars().all()

    async def bulk_insert(self, chunks: Iterable[ChunkInput]) -> int:
        """Insert a batch of chunks (used by P1)."""
        rows = [
            Chunk(
                id=c.id,
                episode_id=c.episode_id,
                shot_id=c.shot_id,
                idx=c.idx,
                text=c.text,
                text_normalized=c.text_normalized,
                subtitle_text=c.subtitle_text,
                status="pending",
                boundary_hash=c.boundary_hash,
                char_count=c.char_count,
                extra_metadata=c.metadata,
            )
            for c in chunks
        ]
        self.session.add_all(rows)
        await self.session.flush()
        return len(rows)

    async def set_subtitle_cues(
        self,
        chunk_id: str,
        cues: list[dict[str, Any]],
    ) -> None:
        """Persist P5 cues into ``chunks.metadata["subtitle_cues"]``.

        The metadata JSONB is a grab-bag of user- and pipeline-owned keys.
        We read → merge → write so that other keys (e.g. P1 ``segment_type``)
        are preserved. The operation is a single UPDATE within the caller's
        transaction; atomicity against concurrent edits on the same chunk
        relies on the caller's unit-of-work, which matches the rest of this
        repo.

        Called by :mod:`server.flows.tasks.p5_subtitles` right after the
        SRT document is uploaded, so the SRT and the metadata cue list are
        committed together.
        """
        chunk = await self.session.get(Chunk, chunk_id)
        if chunk is None:
            raise LookupError(f"chunk not found: {chunk_id}")
        new_meta = dict(chunk.extra_metadata or {})
        new_meta["subtitle_cues"] = cues
        stmt = (
            update(Chunk)
            .where(Chunk.id == chunk_id)
            .values(extra_metadata=new_meta)
        )
        await self.session.execute(stmt)

    async def apply_edits(self, edits: Iterable[ChunkEdit]) -> int:
        """Apply a batch of sparse edits **atomically**.

        Any failure rolls back the savepoint — the caller's outer transaction
        stays intact so it can decide whether to retry or abort.
        Returns the number of chunks updated.
        """
        edits = list(edits)
        if not edits:
            return 0

        now = datetime.now(timezone.utc)
        async with self.session.begin_nested():
            updated = 0
            for edit in edits:
                values: dict[str, Any] = {}
                if edit.text is not None:
                    values["text"] = edit.text
                if edit.text_normalized is not None:
                    values["text_normalized"] = edit.text_normalized
                if edit.subtitle_text is not None:
                    values["subtitle_text"] = edit.subtitle_text
                if edit.metadata is not None:
                    values["extra_metadata"] = edit.metadata
                if not values:
                    continue
                values["last_edited_at"] = now
                # Also recompute char_count if text_normalized changed.
                if edit.text_normalized is not None:
                    values["char_count"] = len(edit.text_normalized)
                stmt = (
                    update(Chunk)
                    .where(Chunk.id == edit.chunk_id)
                    .values(**values)
                )
                res = await self.session.execute(stmt)
                affected = res.rowcount or 0
                if affected == 0:
                    raise LookupError(f"chunk not found: {edit.chunk_id}")
                updated += affected
            return updated

    async def set_status(self, chunk_id: str, status: str) -> bool:
        stmt = update(Chunk).where(Chunk.id == chunk_id).values(status=status)
        res = await self.session.execute(stmt)
        return (res.rowcount or 0) > 0

    async def set_selected_take(self, chunk_id: str, take_id: str | None) -> bool:
        stmt = (
            update(Chunk)
            .where(Chunk.id == chunk_id)
            .values(selected_take_id=take_id)
        )
        res = await self.session.execute(stmt)
        return (res.rowcount or 0) > 0


# ---------------------------------------------------------------------------
# Takes
# ---------------------------------------------------------------------------


class TakeRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def append(self, payload: TakeAppend) -> Take:
        take = Take(
            id=payload.id,
            chunk_id=payload.chunk_id,
            audio_uri=payload.audio_uri,
            duration_s=payload.duration_s,
            params=payload.params,
        )
        self.session.add(take)
        await self.session.flush()
        return take

    async def select(self, take_id: str) -> Take | None:
        return await self.session.get(Take, take_id)

    async def list_by_chunk(self, chunk_id: str) -> Sequence[Take]:
        stmt = (
            select(Take)
            .where(Take.chunk_id == chunk_id)
            .order_by(Take.created_at.asc())
        )
        res = await self.session.execute(stmt)
        return res.scalars().all()

    async def remove(self, take_id: str) -> bool:
        stmt = delete(Take).where(Take.id == take_id)
        res = await self.session.execute(stmt)
        return (res.rowcount or 0) > 0


# ---------------------------------------------------------------------------
# Stage runs
# ---------------------------------------------------------------------------


class StageRunRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, chunk_id: str, stage: str) -> StageRun | None:
        stmt = select(StageRun).where(
            StageRun.chunk_id == chunk_id, StageRun.stage == stage
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def list_by_chunk(self, chunk_id: str) -> Sequence[StageRun]:
        stmt = (
            select(StageRun)
            .where(StageRun.chunk_id == chunk_id)
            .order_by(StageRun.stage)
        )
        res = await self.session.execute(stmt)
        return res.scalars().all()

    async def upsert(
        self,
        *,
        chunk_id: str,
        stage: str,
        status: str,
        attempt: int | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        duration_ms: int | None = None,
        error: str | None = None,
        log_uri: str | None = None,
        prefect_task_run_id: Any = None,
        stale: bool | None = None,
    ) -> StageRun:
        existing = await self.get(chunk_id, stage)
        if existing is None:
            row = StageRun(
                chunk_id=chunk_id,
                stage=stage,
                status=status,
                attempt=attempt or 0,
                started_at=started_at,
                finished_at=finished_at,
                duration_ms=duration_ms,
                error=error,
                log_uri=log_uri,
                prefect_task_run_id=prefect_task_run_id,
                stale=bool(stale) if stale is not None else False,
            )
            self.session.add(row)
            await self.session.flush()
            return row

        # Update in place.
        existing.status = status
        if attempt is not None:
            existing.attempt = attempt
        if started_at is not None:
            existing.started_at = started_at
        if finished_at is not None:
            existing.finished_at = finished_at
        if duration_ms is not None:
            existing.duration_ms = duration_ms
        if error is not None:
            existing.error = error
        if log_uri is not None:
            existing.log_uri = log_uri
        if prefect_task_run_id is not None:
            existing.prefect_task_run_id = prefect_task_run_id
        if stale is not None:
            existing.stale = stale
        await self.session.flush()
        return existing


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


class EventRepo:
    """Thin wrapper around ``events.write_event``.

    Keeping the implementation in a module-level function makes it easy to
    call from places that don't want to instantiate a repo (e.g. tests), and
    the class here is just for dependency-injection ergonomics in the API
    layer.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def write(
        self,
        *,
        episode_id: str,
        chunk_id: str | None,
        kind: str,
        payload: dict[str, Any],
    ) -> int:
        return await events_module.write_event(
            self.session,
            episode_id=episode_id,
            chunk_id=chunk_id,
            kind=kind,
            payload=payload,
        )

    async def list_since(
        self, episode_id: str, *, after_id: int = 0, limit: int = 100
    ) -> Sequence[Event]:
        stmt = (
            select(Event)
            .where(Event.episode_id == episode_id, Event.id > after_id)
            .order_by(Event.id.asc())
            .limit(limit)
        )
        res = await self.session.execute(stmt)
        return res.scalars().all()

    async def list_recent(
        self, episode_id: str, *, limit: int = 100
    ) -> Sequence[Event]:
        """Return the most recent *limit* events, ordered oldest-first."""
        # Sub-select newest N, then re-order ascending for display.
        inner = (
            select(Event)
            .where(Event.episode_id == episode_id)
            .order_by(Event.id.desc())
            .limit(limit)
            .subquery()
        )
        stmt = select(Event).join(inner, Event.id == inner.c.id).order_by(Event.id.asc())
        res = await self.session.execute(stmt)
        return res.scalars().all()

    async def count(self, episode_id: str) -> int:
        stmt = select(func.count()).select_from(Event).where(
            Event.episode_id == episode_id
        )
        res = await self.session.execute(stmt)
        return int(res.scalar_one())


__all__ = [
    "EpisodeRepo",
    "ChunkRepo",
    "TakeRepo",
    "StageRunRepo",
    "EventRepo",
]
