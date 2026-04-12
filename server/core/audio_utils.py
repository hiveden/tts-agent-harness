"""Audio analysis utilities — thin wrappers around ffmpeg/ffprobe.

All functions in this module shell out to ffmpeg binaries. They are
deterministic given the same input WAV and parameters.
"""

from __future__ import annotations

import re
import subprocess


def detect_silence(
    wav_path: str,
    threshold_db: int = -30,
    min_duration: float = 0.3,
) -> list[dict]:
    """Call ffmpeg silencedetect and return a list of silence segments.

    Each segment is ``{"start": float, "end": float, "duration": float}``.
    """
    cmd = [
        "ffmpeg", "-i", wav_path,
        "-af", f"silencedetect=noise={threshold_db}dB:d={min_duration}",
        "-f", "null", "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

    segments: list[dict] = []
    starts = re.findall(r"silence_start: ([\d.]+)", result.stderr)
    ends = re.findall(r"silence_end: ([\d.]+)", result.stderr)
    for s, e in zip(starts, ends):
        start_f = float(s)
        end_f = float(e)
        segments.append({
            "start": start_f,
            "end": end_f,
            "duration": round(end_f - start_f, 6),
        })
    return segments


__all__ = ["detect_silence"]
