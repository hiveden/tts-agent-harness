"""Fish Audio TTS HTTP client.

This is a thin, **mock-friendly** async wrapper around ``httpx`` for the
Fish Audio ``/v1/tts`` endpoint. Retry / rate-limit backoff is intentionally
**not** implemented here — per ADR-001 §4.3 those concerns live at the
Prefect task layer (``tags=["fish-api"]`` + ``retries=N``). The client's
only job is to:

1. Shape the request body from a :class:`FishTTSParams`.
2. Execute the HTTP call.
3. Classify the response into one of the four exception categories so
   that Prefect's retry policy can decide whether to back off.

Exception taxonomy
------------------
``FishAuthError``       — 401/403, fatal, never retried.
``FishRateLimitError``  — 429, retryable (Prefect retries).
``FishServerError``     — 5xx, retryable.
``FishClientError``     — other 4xx or malformed body, fatal.

Network-level failures (``httpx.TimeoutException`` /
``httpx.TransportError``) are allowed to bubble up unchanged so Prefect's
generic retry mechanism can catch them.

The constructor accepts an optional ``httpx.AsyncClient`` — in tests we
inject a client built around ``httpx.MockTransport``; in production the
client creates its own with a sensible default timeout.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import httpx

from .domain import FishTTSParams

FISH_TTS_URL = "https://api.fish.audio/v1/tts"
DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)


# ---------------------------------------------------------------------------
# Exception taxonomy
# ---------------------------------------------------------------------------


class FishTTSError(Exception):
    """Base class for all Fish API errors classified by this client."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class FishAuthError(FishTTSError):
    """401 / 403 — do not retry, credentials problem."""


class FishRateLimitError(FishTTSError):
    """429 — retryable at the Prefect layer."""


class FishServerError(FishTTSError):
    """5xx — retryable at the Prefect layer."""


class FishClientError(FishTTSError):
    """Other 4xx, empty body, or malformed response — not retryable."""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class FishTTSClient:
    """Async Fish Audio TTS client.

    Usage
    -----
    Production::

        client = FishTTSClient(api_key=os.environ["FISH_TTS_KEY"])
        wav = await client.synthesize("hello world", FishTTSParams())

    Tests::

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http:
            client = FishTTSClient(api_key="test", http_client=http)
            wav = await client.synthesize("hello", FishTTSParams())
    """

    def __init__(
        self,
        *,
        api_key: str,
        http_client: httpx.AsyncClient | None = None,
        url: str = FISH_TTS_URL,
    ) -> None:
        if not api_key:
            raise ValueError("FishTTSClient requires a non-empty api_key")
        self._api_key = api_key
        self._url = url
        self._http = http_client
        self._owns_http = http_client is None

    # ----- HTTP lifecycle ----------------------------------------------

    async def aclose(self) -> None:
        if self._owns_http and self._http is not None:
            await self._http.aclose()
            self._http = None

    @asynccontextmanager
    async def _client(self) -> AsyncIterator[httpx.AsyncClient]:
        if self._http is not None:
            yield self._http
            return
        # Lazily create a long-lived client on first use.
        self._http = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
        yield self._http

    # ----- public API --------------------------------------------------

    def build_payload(self, text: str, params: FishTTSParams) -> dict[str, Any]:
        """Return the JSON body that Fish expects.

        Exposed as a method (not a private helper) so tests can assert the
        exact wire shape without mocking the HTTP layer.
        """
        body: dict[str, Any] = {
            "text": text,
            "format": params.format,
            "mp3_bitrate": params.mp3_bitrate,
            "normalize": params.normalize,
            "latency": params.latency,
            "model": params.model,
            "temperature": params.temperature,
            "top_p": params.top_p,
            "chunk_length": params.chunk_length,
        }
        if params.reference_id:
            body["reference_id"] = params.reference_id
        return body

    async def synthesize(self, text: str, params: FishTTSParams) -> bytes:
        """POST text, return raw WAV bytes.

        Raises :class:`FishTTSError` subclasses on HTTP-level failures.
        Lets network-level exceptions from httpx propagate unchanged (so
        that Prefect's retry layer can catch ``httpx.TimeoutException``).
        """
        if not text or not text.strip():
            raise FishClientError("cannot synthesize empty text")

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": f"audio/{params.format}" if params.format else "*/*",
        }
        payload = self.build_payload(text, params)

        try:
            async with self._client() as http:
                response = await http.post(self._url, json=payload, headers=headers)
        except Exception as exc:
            raise FishClientError(
                f"Failed to connect to Fish TTS at {self._url}: {type(exc).__name__}: {exc}",
            ) from exc

        return self._handle_response(response)

    # ----- internal ----------------------------------------------------

    def _handle_response(self, response: httpx.Response) -> bytes:
        status = response.status_code

        if 200 <= status < 300:
            data = response.content
            if not data:
                raise FishClientError(
                    "Fish API returned 2xx with empty body",
                    status_code=status,
                )
            return data

        # Try to pull a useful error message out of the body.
        try:
            detail = response.text[:500]
        except Exception:  # pragma: no cover
            detail = "<unreadable>"

        if status in (401, 403):
            raise FishAuthError(
                f"Fish API auth error {status}: {detail}", status_code=status
            )
        if status == 429:
            raise FishRateLimitError(
                f"Fish API rate limited: {detail}", status_code=status
            )
        if 500 <= status < 600:
            raise FishServerError(
                f"Fish API server error {status}: {detail}", status_code=status
            )
        raise FishClientError(
            f"Fish API client error {status}: {detail}", status_code=status
        )


# ---------------------------------------------------------------------------
# Factory helper
# ---------------------------------------------------------------------------


def build_params_from_env(overrides: dict[str, Any] | None = None) -> FishTTSParams:
    """Construct :class:`FishTTSParams` using env-var defaults.

    Precedence: ``overrides`` > env vars > :class:`FishTTSParams` defaults.
    This is called from ``p2_synth`` so that all env-coupling lives in one
    place and the rest of the module stays pure.
    """
    base: dict[str, Any] = {}
    if ref := os.environ.get("FISH_TTS_REFERENCE_ID"):
        base["reference_id"] = ref
    if model := os.environ.get("FISH_TTS_MODEL"):
        base["model"] = model
    if overrides:
        base.update(overrides)
    return FishTTSParams(**base)


__all__ = [
    "FishTTSClient",
    "FishTTSError",
    "FishAuthError",
    "FishRateLimitError",
    "FishServerError",
    "FishClientError",
    "FISH_TTS_URL",
    "build_params_from_env",
]
