"""SQLAlchemy 2.x ORM models for the TTS Agent Harness business schema.

Mirrors the DDL in ADR-001 §5.1. The physical Postgres schema is managed by
alembic (A1). These ORM classes are the read/write façade used by the async
repositories. They are database-portable enough that the same models can run
against SQLite (for dev / tests) via ``Base.metadata.create_all``.

Portability notes:
- ``JSONB`` is a Postgres-specific type. We fall back to generic JSON so that
  SQLite can execute the ``create_all`` path cleanly.
- ``TIMESTAMPTZ`` is expressed as ``DateTime(timezone=True)``.
- ``BIGSERIAL`` is ``BigInteger`` + ``autoincrement=True``.
- ``UUID`` for ``prefect_task_run_id`` uses SQLAlchemy's dialect-agnostic
  ``Uuid`` type added in SA 2.0.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    REAL,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


# ``JSONB`` on Postgres, generic ``JSON`` elsewhere (SQLite tests).
JsonType = JSONB().with_variant(JSON(), "sqlite")

# ``REAL`` (float4) on Postgres per ADR-001 §5.1, generic ``Float`` on SQLite.
RealType = REAL().with_variant(Float(), "sqlite")


class Episode(Base):
    __tablename__ = "episodes"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    script_uri: Mapped[str] = mapped_column(Text, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(
        JsonType, nullable=False, default=dict, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    locked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    extra_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JsonType,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="episode",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    events: Mapped[list["Event"]] = relationship(
        back_populates="episode",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint(
            "episode_id",
            "shot_id",
            "idx",
            name="chunks_episode_shot_idx_key",
        ),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    episode_id: Mapped[str] = mapped_column(
        Text, ForeignKey("episodes.id", ondelete="CASCADE"), nullable=False
    )
    shot_id: Mapped[str] = mapped_column(Text, nullable=False)
    idx: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_normalized: Mapped[str] = mapped_column(Text, nullable=False)
    subtitle_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    selected_take_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    boundary_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)
    last_edited_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    normalized_history: Mapped[list[Any]] = mapped_column(
        JsonType, nullable=False, default=list, server_default="[]"
    )
    extra_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JsonType,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    episode: Mapped[Episode] = relationship(back_populates="chunks")
    takes: Mapped[list["Take"]] = relationship(
        back_populates="chunk",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    stage_runs: Mapped[list["StageRun"]] = relationship(
        back_populates="chunk",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    events: Mapped[list["Event"]] = relationship(
        back_populates="chunk",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Take(Base):
    __tablename__ = "takes"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    chunk_id: Mapped[str] = mapped_column(
        Text, ForeignKey("chunks.id", ondelete="CASCADE"), nullable=False
    )
    audio_uri: Mapped[str] = mapped_column(Text, nullable=False)
    # ADR-001 §5.1: REAL (float4 on Postgres). Aligned with V001_initial.py.
    duration_s: Mapped[float] = mapped_column(RealType, nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(
        JsonType, nullable=False, default=dict, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    chunk: Mapped[Chunk] = relationship(back_populates="takes")


class StageRun(Base):
    __tablename__ = "stage_runs"

    chunk_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("chunks.id", ondelete="CASCADE"),
        primary_key=True,
    )
    stage: Mapped[str] = mapped_column(Text, primary_key=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    log_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    prefect_task_run_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    chunk: Mapped[Chunk] = relationship(back_populates="stage_runs")


class Event(Base):
    __tablename__ = "events"
    # ADR-001 §5.1 + V001_initial.py: composite index on (episode_id, id DESC)
    # — feed pattern is "newest events for an episode first" (SSE replay).
    __table_args__ = (
        Index(
            "events_episode_idx",
            "episode_id",
            text("id DESC"),
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    episode_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("episodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_id: Mapped[str | None] = mapped_column(
        Text,
        ForeignKey("chunks.id", ondelete="CASCADE"),
        nullable=True,
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JsonType, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    episode: Mapped["Episode"] = relationship(back_populates="events")
    chunk: Mapped["Chunk | None"] = relationship(back_populates="events")


__all__ = [
    "Base",
    "Episode",
    "Chunk",
    "Take",
    "StageRun",
    "Event",
]
