"""Pydantic v2 schemas — the single source of truth for API + flow contracts.

This module MUST NOT contain business logic. Only data shapes. All models use
``ConfigDict(from_attributes=True)`` so that they can be produced directly from
SQLAlchemy ORM instances via ``Model.model_validate(orm_obj)``.

Naming convention
-----------------
- ``*Input`` / ``*Create`` / ``*Edit`` / ``*Append`` — write-side payloads
- ``*View``                                            — read-side projections
- ``P{n}Result``                                       — pipeline stage results
- ``StageEvent``                                       — SSE / NOTIFY payload
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

# ---------------------------------------------------------------------------
# Common type aliases
# ---------------------------------------------------------------------------

EpisodeStatus = Literal["empty", "ready", "running", "failed", "done"]
ChunkStatus = Literal["pending", "synth_done", "verified", "needs_review", "failed"]
StageName = Literal["p1", "p1c", "p2", "p2c", "p2v", "p3", "p5", "p6", "p6v"]
StageStatus = Literal["pending", "running", "ok", "failed"]
EventKind = Literal[
    "stage_started",
    "stage_finished",
    "stage_failed",
    "stage_retry",
    "take_appended",
    "take_finalized",
    "chunk_edited",
    "episode_created",
    "episode_status_changed",
    "verify_started",
    "verify_finished",
    "verify_failed",
    "repair_decided",
    "needs_review",
    "review_reset",
]


class DomainError(Exception):
    """Raised by core logic / Prefect tasks on expected business failures.

    The ``code`` is a short machine-readable token (``not_found``,
    ``invalid_state``, ``invalid_input`` ...). Callers can branch on it
    without pattern-matching exception messages.
    """

    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(message or code)
        self.code = code
        self.message = message or code


class _CamelBase(BaseModel):
    """Base for all API-facing models. Serializes to camelCase for OpenAPI/JSON."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,  # Python code still uses snake_case
    )


class _ORM(_CamelBase):
    """Base class for ORM-backed read models."""

    model_config = ConfigDict(
        from_attributes=True,
        alias_generator=to_camel,
        populate_by_name=True,
    )


# ---------------------------------------------------------------------------
# Write-side payloads
# ---------------------------------------------------------------------------


class EpisodeCreate(_CamelBase):
    """Input for creating a new episode."""

    id: str
    title: str
    description: str | None = None
    script_uri: str
    config: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChunkInput(_CamelBase):
    """Shape consumed by P1 → DB (one row per chunk)."""

    id: str
    episode_id: str
    shot_id: str
    idx: int
    text: str
    text_normalized: str
    subtitle_text: str | None = None
    char_count: int
    boundary_hash: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChunkEdit(_CamelBase):
    """User edit applied to a chunk. All fields optional — sparse update."""

    chunk_id: str
    text: str | None = None
    text_normalized: str | None = None
    subtitle_text: str | None = None
    metadata: dict[str, Any] | None = None


class TakeAppend(_CamelBase):
    """Payload for appending a new take after a P2 synth."""

    id: str
    chunk_id: str
    audio_uri: str
    duration_s: float
    params: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Read-side views
# ---------------------------------------------------------------------------


class TakeView(_ORM):
    id: str
    chunk_id: str
    audio_uri: str
    duration_s: float
    params: dict[str, Any]
    created_at: datetime


class StageRunView(_ORM):
    chunk_id: str
    stage: str
    status: StageStatus
    attempt: int
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    error: str | None
    log_uri: str | None
    prefect_task_run_id: UUID | None
    stale: bool


class ChunkView(_ORM):
    id: str
    episode_id: str
    shot_id: str
    idx: int
    text: str
    text_normalized: str
    subtitle_text: str | None
    status: ChunkStatus
    selected_take_id: str | None
    boundary_hash: str | None
    char_count: int
    last_edited_at: datetime | None
    extra_metadata: dict[str, Any] = Field(default_factory=dict, serialization_alias="metadata")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class EpisodeView(_ORM):
    id: str
    title: str
    description: str | None
    status: EpisodeStatus
    script_uri: str
    config: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    extra_metadata: dict[str, Any] = Field(default_factory=dict, serialization_alias="metadata")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class EpisodeSummary(_CamelBase):
    """Aggregated view for listing pages."""

    id: str
    title: str
    status: EpisodeStatus
    chunk_count: int
    done_count: int
    failed_count: int
    updated_at: datetime


# ---------------------------------------------------------------------------
# Pipeline stage results (flow-task contracts)
# ---------------------------------------------------------------------------


class P1Result(_CamelBase):
    episode_id: str
    chunks: list[ChunkInput]


class P2Result(_CamelBase):
    chunk_id: str
    take_id: str
    audio_uri: str
    duration_s: float
    params: dict[str, Any] = Field(default_factory=dict)


class FishTTSParams(_CamelBase):
    """Full parameter surface for a Fish Audio TTS S2-Pro call.

    Defaults are safe production values. Overrides flow in from
    environment variables at task-boundary level (not here): keeping this
    schema free of env coupling makes it trivial to serialize into the
    ``takes.params`` JSON column for audit.
    """

    reference_id: str | None = None
    model: str = "s2-pro"
    format: Literal["wav", "mp3", "pcm"] = "wav"
    mp3_bitrate: int = 192
    normalize: bool = False
    latency: Literal["normal", "balanced"] = "normal"
    temperature: float = 0.7
    top_p: float = 0.7
    chunk_length: int = 200


class P2vResult(_CamelBase):
    """Result of the P2v verify task (ASR + quality check)."""

    chunk_id: str
    verdict: Literal["pass", "fail"]
    char_ratio: float
    transcript_uri: str | None = None
    transcribed_text: str = ""
    original_text: str = ""


class P3Result(_CamelBase):
    chunk_id: str
    transcript_uri: str
    word_count: int


class P5Result(_CamelBase):
    chunk_id: str
    subtitle_uri: str
    line_count: int = 0


class WhisperXWord(_CamelBase):
    """Single word-level timestamp emitted by the WhisperX service.

    ``score`` is optional because forced-aligned words without a confidence
    still carry useful start/end timestamps, and downstream ranking code is
    allowed to ignore it.
    """

    word: str
    start: float
    end: float
    score: float | None = None


class WhisperXTranscript(_CamelBase):
    """Shape of ``transcript.json`` produced by the WhisperX HTTP service.

    Only the fields consumed by P5 are modelled; anything else is permitted
    and silently ignored so the wire schema can evolve without breaking P5.
    """

    transcript: list[WhisperXWord] = Field(default_factory=list)
    language: str | None = None
    duration_s: float | None = None
    model: str | None = None

    model_config = ConfigDict(extra="ignore")


class P6Result(_CamelBase):
    """Episode-level concat result emitted by the P6 task.

    Field names match the A7-P6 agent contract (``wav_uri`` / ``srt_uri`` /
    ``total_duration_s`` / ``chunk_count``) — P6 is the terminal per-episode
    stage and these names read more naturally at the API boundary than the
    generic ``final_*_uri`` shape used by earlier drafts.
    """

    episode_id: str
    wav_uri: str
    srt_uri: str
    total_duration_s: float
    chunk_count: int


# ---------------------------------------------------------------------------
# Events (SSE payload)
# ---------------------------------------------------------------------------


class StageEvent(_CamelBase):
    """Event broadcast on the `episode_events` NOTIFY channel.

    The ``id`` field is assigned by the DB (bigserial); the producer code
    sets it after insert for convenience.
    """

    id: int | None = None
    episode_id: str
    chunk_id: str | None = None
    kind: EventKind
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


__all__ = [
    # aliases
    "EpisodeStatus",
    "ChunkStatus",
    "StageName",
    "StageStatus",
    "EventKind",
    # errors
    "DomainError",
    # write
    "EpisodeCreate",
    "ChunkInput",
    "ChunkEdit",
    "TakeAppend",
    # read
    "TakeView",
    "StageRunView",
    "ChunkView",
    "EpisodeView",
    "EpisodeSummary",
    # stages
    "P1Result",
    "P2Result",
    "P2vResult",
    "FishTTSParams",
    "P3Result",
    "P5Result",
    "WhisperXWord",
    "WhisperXTranscript",
    "P6Result",
    # events
    "StageEvent",
]
