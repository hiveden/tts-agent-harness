"""Export logic — build Remotion-compatible zip from episode chunks.

Pure async function, no FastAPI dependencies. Can be called from:
- API route (dev mode background task)
- Prefect flow (production)

Produces a zip stored in MinIO at ``exports/{episode_id}.zip``.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import tempfile
import wave
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from server.core.domain import DomainError
from server.core.events import write_event
from server.core.p6_logic import (
    ChunkTiming,
    compute_chunk_offsets,
    generate_silence,
    parse_srt,
    sort_chunk_timings,
)
from server.core.repositories import ChunkRepo, EpisodeRepo, TakeRepo
from server.core.storage import MinIOStorage, chunk_subtitle_key

log = logging.getLogger(__name__)

PADDING_S = 0.2
SHOT_GAP_S = 0.5


def export_zip_key(episode_id: str) -> str:
    """MinIO key for export zip."""
    return f"exports/{episode_id}.zip"


async def run_export(
    episode_id: str,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    storage: MinIOStorage,
) -> str:
    """Build export zip and upload to MinIO. Returns the MinIO key.

    Emits SSE events: export_started, export_finished, export_failed.
    """
    zip_key = export_zip_key(episode_id)

    # Emit export_started
    async with session_factory() as session:
        await write_event(
            session,
            episode_id=episode_id,
            chunk_id=None,
            kind="export_started",
            payload={},
        )
        await session.commit()

    try:
        zip_bytes = await _build_zip(episode_id, session_factory=session_factory, storage=storage)
    except Exception as exc:
        # Emit export_failed
        async with session_factory() as session:
            await write_event(
                session,
                episode_id=episode_id,
                chunk_id=None,
                kind="export_failed",
                payload={"error": f"{type(exc).__name__}: {exc}"},
            )
            await session.commit()
        raise

    # Upload to MinIO
    await storage.upload_bytes(zip_key, zip_bytes, content_type="application/zip")

    # Emit export_finished
    async with session_factory() as session:
        await write_event(
            session,
            episode_id=episode_id,
            chunk_id=None,
            kind="export_finished",
            payload={"zip_key": zip_key, "size_bytes": len(zip_bytes)},
        )
        await session.commit()

    return zip_key


async def _build_zip(
    episode_id: str,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    storage: MinIOStorage,
) -> bytes:
    """Build the zip file in memory and return raw bytes."""

    # Load chunks + takes
    async with session_factory() as session:
        ep = await EpisodeRepo(session).get(episode_id)
        if ep is None:
            raise DomainError("not_found", f"episode '{episode_id}' not found")

        chunks = await ChunkRepo(session).list_by_episode(episode_id)
        take_repo = TakeRepo(session)

        items_by_shot: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for c in sorted(chunks, key=lambda c: (c.shot_id, c.idx)):
            if c.selected_take_id and c.status in ("verified", "synth_done"):
                take = await take_repo.select(c.selected_take_id)
                if take:
                    items_by_shot[c.shot_id].append({
                        "chunk_id": c.id,
                        "idx": c.idx,
                        "take_audio_uri": take.audio_uri,
                        "take_duration_s": float(take.duration_s or 0.0),
                    })

    if not items_by_shot:
        raise DomainError("invalid_state", "no verified chunks to export")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        durations: list[dict[str, Any]] = []
        all_subtitles: dict[str, list[dict[str, Any]]] = {}

        for shot_id, items in items_by_shot.items():
            timings = sort_chunk_timings([
                ChunkTiming(
                    chunk_id=item["chunk_id"],
                    shot_id=shot_id,
                    idx=item["idx"],
                    duration_s=item["take_duration_s"],
                )
                for item in items
            ])
            offsets = compute_chunk_offsets(timings, PADDING_S, SHOT_GAP_S)

            # Build per-shot WAV
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                concat_entries: list[Path] = []

                sil_padding = tmp_path / "sil_padding.wav"
                await generate_silence(sil_padding, PADDING_S, sample_rate=44100)

                for i, (timing, item) in enumerate(zip(timings, items)):
                    audio_uri = item["take_audio_uri"]
                    audio_key = (
                        audio_uri.split("//", 1)[-1].split("/", 1)[-1]
                        if audio_uri.startswith("s3://")
                        else audio_uri
                    )
                    try:
                        wav_bytes = await storage.download_bytes(audio_key)
                    except Exception:
                        continue
                    chunk_wav = tmp_path / f"chunk_{i:03d}.wav"
                    chunk_wav.write_bytes(wav_bytes)

                    if i > 0:
                        concat_entries.append(sil_padding)
                    concat_entries.append(chunk_wav)

                if not concat_entries:
                    continue

                if len(concat_entries) == 1:
                    shot_wav_bytes = concat_entries[0].read_bytes()
                else:
                    concat_list = tmp_path / "concat.txt"
                    concat_list.write_text(
                        "\n".join(f"file '{p.resolve()}'" for p in concat_entries)
                    )
                    shot_wav = tmp_path / f"{shot_id}.wav"
                    proc = await asyncio.create_subprocess_exec(
                        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                        "-f", "concat", "-safe", "0",
                        "-i", str(concat_list),
                        "-ar", "44100", "-ac", "1", "-c:a", "pcm_s16le",
                        str(shot_wav),
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    _, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
                    if proc.returncode != 0:
                        log.warning("ffmpeg concat failed for %s: %s", shot_id, stderr.decode()[:200])
                        continue
                    shot_wav_bytes = shot_wav.read_bytes()

                zf.writestr(f"{episode_id}/{shot_id}.wav", shot_wav_bytes)

                try:
                    with io.BytesIO(shot_wav_bytes) as wio:
                        with wave.open(wio) as wf:
                            dur = wf.getnframes() / wf.getframerate()
                except Exception:
                    dur = sum(item["take_duration_s"] for item in items)

                durations.append({
                    "id": shot_id,
                    "duration_s": round(dur, 3),
                    "file": f"{shot_id}.wav",
                })

            # Subtitles
            shot_subs: list[dict[str, Any]] = []
            sub_counter = sum(len(subs) for subs in all_subtitles.values())
            for timing, offset in zip(timings, offsets):
                sub_key = chunk_subtitle_key(episode_id, timing.chunk_id)
                try:
                    srt_bytes = await storage.download_bytes(sub_key)
                    cues = parse_srt(srt_bytes.decode("utf-8"))
                except Exception:
                    continue
                for cue in cues:
                    sub_counter += 1
                    shot_subs.append({
                        "id": f"sub_{sub_counter:03d}",
                        "text": cue.text,
                        "start": round(cue.start_s + offset, 3),
                        "end": round(cue.end_s + offset, 3),
                    })
            if shot_subs:
                all_subtitles[shot_id] = shot_subs

        zf.writestr(
            f"{episode_id}/subtitles.json",
            json.dumps(all_subtitles, ensure_ascii=False, indent=2),
        )
        zf.writestr(
            f"{episode_id}/durations.json",
            json.dumps(durations, ensure_ascii=False, indent=2),
        )

    return buf.getvalue()
