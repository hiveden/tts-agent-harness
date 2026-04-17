"""P2c — WAV format validation check gate, runs after P2 and before P3.

Validates each chunk's synthesized WAV file to catch format issues before
sending to the expensive ASR pipeline.

Check rules (per-chunk):
  - WAV file exists in storage       (hard fail)
  - 0 < duration < 60s               (hard fail)
  - sample rate == 44100Hz            (hard fail)
  - mono (1 channel)                  (hard fail)
  - speech rate 2-12 chars/s          (warning, not fail)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable

from prefect import task
from sqlalchemy.ext.asyncio import AsyncSession

from server.core.domain import DomainError
from server.core.events import write_event
from server.core.repositories import ChunkRepo, StageRunRepo, TakeRepo
from server.core.storage import MinIOStorage

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Dependency wiring
# ---------------------------------------------------------------------------

_SessionFactory = Callable[[], Any]
_session_factory: _SessionFactory | None = None
_storage: MinIOStorage | None = None


def configure_p2c_dependencies(
    *,
    session_factory: _SessionFactory,
    storage: MinIOStorage,
) -> None:
    global _session_factory, _storage
    _session_factory = session_factory
    _storage = storage


def _require_deps() -> tuple[_SessionFactory, MinIOStorage]:
    if _session_factory is None or _storage is None:
        raise RuntimeError(
            "p2c_check dependencies not configured. "
            "Call configure_p2c_dependencies(...) before running the task."
        )
    return _session_factory, _storage


@asynccontextmanager
async def _session_scope(factory: _SessionFactory) -> AsyncIterator[AsyncSession]:
    ctx = factory()
    async with ctx as session:
        yield session


# ---------------------------------------------------------------------------
# ffprobe helper
# ---------------------------------------------------------------------------


async def _ffprobe_info(wav_path: str) -> dict[str, Any]:
    """Run ffprobe to extract audio stream info. Returns dict with
    sample_rate, channels, duration keys."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-show_entries", "stream=sample_rate,channels",
        "-show_entries", "format=duration",
        "-of", "json",
        wav_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {stderr.decode()}")

    data = json.loads(stdout.decode())
    result: dict[str, Any] = {}

    # Parse stream info
    streams = data.get("streams", [])
    if streams:
        result["sample_rate"] = int(streams[0].get("sample_rate", 0))
        result["channels"] = int(streams[0].get("channels", 0))

    # Parse format duration
    fmt = data.get("format", {})
    dur_str = fmt.get("duration", "0")
    result["duration"] = float(dur_str)

    return result


def validate_wav(
    info: dict[str, Any],
    char_count: int,
) -> tuple[list[str], list[str]]:
    """Validate WAV properties. Returns (errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []

    duration = info.get("duration", 0.0)
    sample_rate = info.get("sample_rate", 0)
    channels = info.get("channels", 0)

    # Duration check
    if duration <= 0:
        errors.append(f"WAV duration is {duration}s (invalid)")
    elif duration > 60:
        errors.append(f"WAV duration {duration:.1f}s exceeds 60s limit")

    # Sample rate check
    if sample_rate != 44100:
        errors.append(f"sample rate {sample_rate} != 44100")

    # Mono check
    if channels != 1:
        errors.append(f"channels {channels} != 1 (mono)")

    # Speech rate check (warning only)
    if duration > 0 and char_count > 0:
        chars_per_sec = char_count / duration
        if chars_per_sec < 2 or chars_per_sec > 12:
            warnings.append(
                f"speech rate {chars_per_sec:.1f} chars/s outside 2-12 range"
            )

    return errors, warnings


# ---------------------------------------------------------------------------
# Core routine
# ---------------------------------------------------------------------------


async def run_p2c_check(chunk_id: str) -> dict[str, Any]:
    """Pure coroutine that executes the P2c WAV check gate."""
    session_factory, storage = _require_deps()

    # 1. Load chunk + take info
    async with _session_scope(session_factory) as session:
        chunk = await ChunkRepo(session).get(chunk_id)
        if chunk is None:
            await _emit_stage_failed(
                session_factory,
                episode_id="unknown",
                chunk_id=chunk_id,
                error=f"chunk not found: {chunk_id}",
            )
            raise DomainError("not_found", f"chunk not found: {chunk_id}")

        episode_id = chunk.episode_id
        char_count = chunk.char_count
        take_id = chunk.selected_take_id

        if not take_id:
            await _emit_stage_failed(
                session_factory,
                episode_id=episode_id,
                chunk_id=chunk_id,
                error=f"chunk {chunk_id} has no selected take",
            )
            raise DomainError("invalid_state", f"chunk {chunk_id} has no selected take")

        take = await TakeRepo(session).select(take_id)
        if take is None:
            await _emit_stage_failed(
                session_factory,
                episode_id=episode_id,
                chunk_id=chunk_id,
                error=f"take not found: {take_id}",
            )
            raise DomainError("not_found", f"take not found: {take_id}")
        audio_uri = take.audio_uri
        # Strip s3://bucket/ prefix to get the MinIO object key
        audio_key = audio_uri.split("//", 1)[-1].split("/", 1)[-1] if audio_uri.startswith("s3://") else audio_uri

        log.info("P2c start chunk=%s take=%s char_count=%d", chunk_id, take_id, char_count)

        # stage_started
        started_at = datetime.now(timezone.utc)
        await write_event(
            session,
            episode_id=episode_id,
            chunk_id=chunk_id,
            kind="stage_started",
            payload={"stage": "p2c", "started_at": started_at.isoformat()},
        )
        await StageRunRepo(session).upsert(
            chunk_id=chunk_id,
            stage="p2c",
            status="running",
            started_at=started_at,
        )
        await session.commit()

    # 2. Download WAV and probe
    errors: list[str] = []
    warnings: list[str] = []

    try:
        wav_bytes = await storage.download_bytes(audio_key)
    except Exception as exc:
        errors.append(f"WAV file not found: {exc}")
        wav_bytes = None

    if wav_bytes:
        # Write to temp file for ffprobe
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(wav_bytes)
            tmp_path = tmp.name

        try:
            info = await _ffprobe_info(tmp_path)
            log.info(
                "P2c probe chunk=%s sample_rate=%s channels=%s duration=%s",
                chunk_id,
                info.get("sample_rate"),
                info.get("channels"),
                info.get("duration"),
            )
            errs, warns = validate_wav(info, char_count)
            errors.extend(errs)
            warnings.extend(warns)
        except Exception as exc:
            errors.append(f"ffprobe failed: {exc}")
        finally:
            os.unlink(tmp_path)

    # 3. Write result
    finished_at = datetime.now(timezone.utc)
    duration_ms = int((finished_at - started_at).total_seconds() * 1000)
    status = "failed" if errors else "ok"

    async with _session_scope(session_factory) as session:
        event_kind = "stage_failed" if errors else "stage_finished"
        payload: dict[str, Any] = {
            "stage": "p2c",
            "errors": errors,
            "warnings": warnings,
        }
        if errors:
            payload["error"] = "; ".join(errors)

        await write_event(
            session,
            episode_id=episode_id,
            chunk_id=chunk_id,
            kind=event_kind,
            payload=payload,
        )
        await StageRunRepo(session).upsert(
            chunk_id=chunk_id,
            stage="p2c",
            status=status,
            finished_at=finished_at,
            duration_ms=duration_ms,
            error="; ".join(errors) if errors else None,
        )
        await session.commit()

    if status == "ok":
        log.info(
            "P2c pass chunk=%s duration_ms=%d warnings=%d",
            chunk_id,
            duration_ms,
            len(warnings),
        )
    else:
        log.info(
            "P2c fail chunk=%s reason=%s",
            chunk_id,
            "; ".join(errors),
        )

    return {
        "chunk_id": chunk_id,
        "status": status,
        "errors": errors,
        "warnings": warnings,
    }


async def _emit_stage_failed(
    session_factory: _SessionFactory,
    *,
    episode_id: str,
    chunk_id: str,
    error: str,
) -> None:
    """Best-effort stage_failed event write — never masks the real error."""
    try:
        async with _session_scope(session_factory) as session:
            await write_event(
                session,
                episode_id=episode_id,
                chunk_id=chunk_id,
                kind="stage_failed",
                payload={"stage": "p2c", "error": error},
            )
            await session.commit()
    except Exception:  # pragma: no cover
        log.exception("failed to emit stage_failed event for chunk %s", chunk_id)


# ---------------------------------------------------------------------------
# Prefect task wrapper
# ---------------------------------------------------------------------------


@task(name="p2c-check", retries=0)
async def p2c_check(chunk_id: str) -> dict[str, Any]:
    """Prefect-wrapped entry point for the P2c WAV check gate."""
    return await run_p2c_check(chunk_id)


__all__ = [
    "p2c_check",
    "run_p2c_check",
    "configure_p2c_dependencies",
    "validate_wav",
]
