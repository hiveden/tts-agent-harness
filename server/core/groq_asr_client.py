"""Groq Whisper ASR HTTP client.

Thin async wrapper around Groq's ``/openai/v1/audio/transcriptions``
endpoint.  Returns data in WhisperX-compatible format so it can be used
as a drop-in alternative to the local WhisperX service.

The response mapping is straightforward:
- Groq ``words`` array  -> WhisperX ``transcript`` array
- Groq ``duration``     -> WhisperX ``duration_s``
- Word-level fields (``word``, ``start``, ``end``) are identical.
- ``score`` is set to ``None`` (Groq doesn't provide word confidence).
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx

log = logging.getLogger(__name__)

GROQ_TRANSCRIPTIONS_URL = "https://api.groq.com/openai/v1/audio/transcriptions"

# Module-level semaphore: limit concurrent Groq requests to avoid 429.
_groq_semaphore = asyncio.Semaphore(3)

_MAX_RETRIES = 5
_INITIAL_BACKOFF = 2.0  # seconds


class GroqASRClient:
    """Async client for Groq Whisper transcription API."""

    def __init__(self, api_key: str, proxy: str | None = None) -> None:
        self._api_key = api_key
        self._proxy = proxy or os.environ.get("HTTPS_PROXY")

    async def transcribe(
        self, wav_bytes: bytes, language: str = "zh"
    ) -> dict[str, Any]:
        """POST audio to Groq Whisper API and return WhisperX-compatible dict.

        Includes concurrency limiting (semaphore) and exponential backoff
        retry on 429 Too Many Requests.

        Returns::

            {
                "transcript": [{"word": "...", "start": 0.1, "end": 0.3, "score": None}, ...],
                "duration_s": 13.62,
            }
        """
        client_kwargs: dict[str, Any] = {
            "timeout": httpx.Timeout(300.0, connect=10.0),
        }
        if self._proxy:
            client_kwargs["proxy"] = self._proxy

        async with _groq_semaphore:
            async with httpx.AsyncClient(**client_kwargs) as client:
                last_exc: Exception | None = None
                for attempt in range(_MAX_RETRIES):
                    response = await client.post(
                        GROQ_TRANSCRIPTIONS_URL,
                        headers={"Authorization": f"Bearer {self._api_key}"},
                        files={"file": ("audio.wav", wav_bytes, "audio/wav")},
                        data={
                            "model": "whisper-large-v3",
                            "response_format": "verbose_json",
                            "timestamp_granularities[]": "word",
                            "language": language,
                        },
                    )
                    if response.status_code == 429:
                        retry_after = response.headers.get("retry-after")
                        backoff = (
                            float(retry_after)
                            if retry_after
                            else _INITIAL_BACKOFF * (2 ** attempt)
                        )
                        log.warning(
                            "Groq 429 rate limited, retry %d/%d after %.1fs",
                            attempt + 1, _MAX_RETRIES, backoff,
                        )
                        last_exc = httpx.HTTPStatusError(
                            "429 Too Many Requests",
                            request=response.request,
                            response=response,
                        )
                        await asyncio.sleep(backoff)
                        continue
                    response.raise_for_status()
                    return self._to_whisperx_format(response.json())

                # All retries exhausted
                raise last_exc  # type: ignore[misc]

    @staticmethod
    def _to_whisperx_format(groq_response: dict[str, Any]) -> dict[str, Any]:
        """Convert Groq Whisper response to WhisperX-compatible format."""
        words = groq_response.get("words", [])
        transcript = [
            {
                "word": w.get("word", ""),
                "start": w.get("start", 0.0),
                "end": w.get("end", 0.0),
                "score": None,
            }
            for w in words
        ]
        return {
            "transcript": transcript,
            "duration_s": groq_response.get("duration", 0.0),
        }
