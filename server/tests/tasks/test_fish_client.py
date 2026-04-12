"""Unit tests for ``server.core.fish_client``.

All HTTP is stubbed via :class:`httpx.MockTransport` — no real network,
no real Fish API key required. The test matrix covers:

- happy path (200 + binary body)
- 401 → FishAuthError (fatal)
- 403 → FishAuthError (fatal, same class as 401)
- 429 → FishRateLimitError (retryable)
- 500 → FishServerError (retryable)
- 400 → FishClientError (fatal)
- empty 200 body → FishClientError
- network timeout → httpx.TimeoutException bubbles up
- empty input text → FishClientError without HTTP call
- request body shape + headers
"""

from __future__ import annotations

import json

import httpx
import pytest

from server.core.domain import FishTTSParams
from server.core.fish_client import (
    FISH_TTS_URL,
    FishAuthError,
    FishClientError,
    FishRateLimitError,
    FishServerError,
    FishTTSClient,
    build_params_from_env,
)

def _make_client(handler) -> FishTTSClient:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport)
    return FishTTSClient(api_key="test-key", http_client=http)


async def test_synthesize_success_returns_bytes():
    wav_bytes = b"RIFF\x00\x00\x00\x00WAVEfake"
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, content=wav_bytes)

    client = _make_client(handler)
    try:
        result = await client.synthesize("hello world", FishTTSParams())
    finally:
        await client.aclose()

    assert result == wav_bytes
    assert captured["url"] == FISH_TTS_URL
    assert captured["method"] == "POST"
    assert captured["auth"] == "Bearer test-key"
    body = captured["body"]
    assert body["text"] == "hello world"
    assert body["format"] == "wav"
    assert body["normalize"] is False
    assert body["model"] == "s2-pro"
    assert body["temperature"] == 0.7
    assert body["top_p"] == 0.7
    assert body["chunk_length"] == 200
    # reference_id absent when not set
    assert "reference_id" not in body


async def test_synthesize_includes_reference_id_when_set():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["reference_id"] == "voice-abc"
        return httpx.Response(200, content=b"RIFFxxx")

    client = _make_client(handler)
    try:
        result = await client.synthesize(
            "hello", FishTTSParams(reference_id="voice-abc")
        )
    finally:
        await client.aclose()
    assert result == b"RIFFxxx"


async def test_synthesize_401_raises_auth_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "bad key"})

    client = _make_client(handler)
    try:
        with pytest.raises(FishAuthError) as excinfo:
            await client.synthesize("hello", FishTTSParams())
    finally:
        await client.aclose()
    assert excinfo.value.status_code == 401


async def test_synthesize_403_raises_auth_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": "forbidden"})

    client = _make_client(handler)
    try:
        with pytest.raises(FishAuthError):
            await client.synthesize("hello", FishTTSParams())
    finally:
        await client.aclose()


async def test_synthesize_429_raises_rate_limit_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "slow down"})

    client = _make_client(handler)
    try:
        with pytest.raises(FishRateLimitError) as excinfo:
            await client.synthesize("hello", FishTTSParams())
    finally:
        await client.aclose()
    assert excinfo.value.status_code == 429


async def test_synthesize_500_raises_server_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal")

    client = _make_client(handler)
    try:
        with pytest.raises(FishServerError) as excinfo:
            await client.synthesize("hello", FishTTSParams())
    finally:
        await client.aclose()
    assert excinfo.value.status_code == 500


async def test_synthesize_400_raises_client_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "bad request"})

    client = _make_client(handler)
    try:
        with pytest.raises(FishClientError) as excinfo:
            await client.synthesize("hello", FishTTSParams())
    finally:
        await client.aclose()
    assert excinfo.value.status_code == 400


async def test_synthesize_empty_body_raises_client_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"")

    client = _make_client(handler)
    try:
        with pytest.raises(FishClientError):
            await client.synthesize("hello", FishTTSParams())
    finally:
        await client.aclose()


async def test_synthesize_timeout_bubbles_up():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out")

    client = _make_client(handler)
    try:
        with pytest.raises(FishClientError, match="TimeoutException"):
            await client.synthesize("hello", FishTTSParams())
    finally:
        await client.aclose()


async def test_synthesize_empty_text_rejected_without_http_call():
    called = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        called["n"] += 1
        return httpx.Response(200, content=b"x")

    client = _make_client(handler)
    try:
        with pytest.raises(FishClientError):
            await client.synthesize("   ", FishTTSParams())
    finally:
        await client.aclose()
    assert called["n"] == 0


async def test_client_rejects_empty_api_key():
    with pytest.raises(ValueError):
        FishTTSClient(api_key="")


def test_build_params_from_env_picks_up_env_vars(monkeypatch):
    monkeypatch.setenv("FISH_TTS_REFERENCE_ID", "env-ref")
    monkeypatch.setenv("FISH_TTS_MODEL", "s2-mini")
    params = build_params_from_env()
    assert params.reference_id == "env-ref"
    assert params.model == "s2-mini"


def test_build_params_from_env_overrides_take_precedence(monkeypatch):
    monkeypatch.setenv("FISH_TTS_MODEL", "s2-mini")
    params = build_params_from_env({"model": "s2-pro", "temperature": 0.3})
    assert params.model == "s2-pro"
    assert params.temperature == 0.3


# ---------------------------------------------------------------------------
# Optional live integration test — only runs when FISH_TTS_KEY is set.
# Explicitly marked so it can be excluded via ``-m "not live"``.
# ---------------------------------------------------------------------------


@pytest.mark.live
@pytest.mark.asyncio
@pytest.mark.skipif(
    "FISH_TTS_KEY" not in __import__("os").environ,
    reason="FISH_TTS_KEY not set — skipping live Fish API test",
)
async def test_live_synthesize_smoke():  # pragma: no cover - network
    import os

    client = FishTTSClient(api_key=os.environ["FISH_TTS_KEY"])
    try:
        wav = await client.synthesize(
            "Hello from the P2 live smoke test.", FishTTSParams()
        )
    finally:
        await client.aclose()
    assert wav[:4] == b"RIFF"
    assert len(wav) > 1000
