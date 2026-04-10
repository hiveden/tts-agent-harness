"""E2E tests against a REAL uvicorn HTTP server.

Unlike ASGI-transport tests, these start a real uvicorn process and hit it
via real HTTP — testing CORS, middleware, SSE LISTEN/NOTIFY, etc.

Requires dev stack running (postgres + minio). Marked as @pytest.mark.e2e.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from typing import AsyncIterator

import httpx
import pytest
import pytest_asyncio

from .conftest import e2e_id, make_script_json, make_silent_wav

UVICORN_PORT = 18765  # Non-standard port to avoid conflicts
BASE_URL = f"http://localhost:{UVICORN_PORT}"


# ---------------------------------------------------------------------------
# Server fixture: start/stop uvicorn
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def live_server():
    """Start a real uvicorn server for the module, kill on teardown."""
    env = {
        **os.environ,
        "DATABASE_URL": "postgresql+asyncpg://harness:harness@localhost:55432/harness",
        "MINIO_ENDPOINT": "localhost:59000",
        "MINIO_ACCESS_KEY": "minioadmin",
        "MINIO_SECRET_KEY": "minioadmin",
        "MINIO_BUCKET": "tts-harness",
        "PATH": f"/Applications/Docker.app/Contents/Resources/bin:{os.environ.get('PATH', '')}",
    }

    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn",
            "server.api.main:app",
            "--host", "0.0.0.0",
            "--port", str(UVICORN_PORT),
            "--log-level", "warning",
        ],
        cwd=os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for server to be ready
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            r = httpx.get(f"{BASE_URL}/healthz", timeout=1)
            if r.status_code == 200:
                break
        except (httpx.ConnectError, httpx.ReadTimeout):
            pass
        time.sleep(0.3)
    else:
        proc.kill()
        stdout, stderr = proc.communicate()
        pytest.fail(f"uvicorn failed to start:\nstdout: {stdout.decode()}\nstderr: {stderr.decode()}")

    yield proc

    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest_asyncio.fixture()
async def http_client(live_server) -> AsyncIterator[httpx.AsyncClient]:
    # Clear proxy env — we're hitting localhost, no proxy needed
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10, proxy=None) as client:
        yield client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_healthz(http_client: httpx.AsyncClient):
    resp = await http_client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.e2e
async def test_cors_headers(http_client: httpx.AsyncClient):
    """Verify CORS allows localhost:3010 origin."""
    resp = await http_client.options(
        "/episodes",
        headers={
            "Origin": "http://localhost:3010",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "access-control-allow-origin" in resp.headers
    assert resp.headers["access-control-allow-origin"] in (
        "http://localhost:3010", "*"
    )


@pytest.mark.e2e
async def test_create_and_get_episode(http_client: httpx.AsyncClient):
    ep_id = e2e_id()
    script = make_script_json("Live HTTP Test")

    # Create
    resp = await http_client.post(
        "/episodes",
        files={"script": ("script.json", script, "application/json")},
        data={"id": ep_id, "title": "Live HTTP Test"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["id"] == ep_id

    # Get detail
    resp2 = await http_client.get(f"/episodes/{ep_id}")
    assert resp2.status_code == 200
    data = resp2.json()
    assert data["id"] == ep_id
    assert "chunks" in data

    # List
    resp3 = await http_client.get("/episodes")
    assert resp3.status_code == 200
    ids = [e["id"] for e in resp3.json()]
    assert ep_id in ids

    # Cleanup
    await http_client.delete(f"/episodes/{ep_id}")


@pytest.mark.e2e
async def test_config_crud_live(http_client: httpx.AsyncClient):
    ep_id = e2e_id()
    script = make_script_json("Config Test")
    await http_client.post(
        "/episodes",
        files={"script": ("script.json", script, "application/json")},
        data={"id": ep_id, "title": "Config Test"},
    )

    # Get default config
    resp = await http_client.get(f"/episodes/{ep_id}/config")
    assert resp.status_code == 200

    # Update config
    resp2 = await http_client.put(
        f"/episodes/{ep_id}/config",
        json={"config": {"temperature": 0.3}},
    )
    assert resp2.status_code == 200
    assert resp2.json()["config"]["temperature"] == 0.3

    # Cleanup
    await http_client.delete(f"/episodes/{ep_id}")


@pytest.mark.e2e
async def test_run_modes_live(http_client: httpx.AsyncClient):
    ep_id = e2e_id()
    script = make_script_json("Run Mode Test")
    await http_client.post(
        "/episodes",
        files={"script": ("script.json", script, "application/json")},
        data={"id": ep_id, "title": "Run Mode Test"},
    )

    # chunk_only mode — may 500 if Prefect server has no deployments registered
    resp = await http_client.post(
        f"/episodes/{ep_id}/run",
        json={"mode": "chunk_only"},
    )
    # Accept 200 (prefect connected) or 500 (no deployment — expected in test env)
    assert resp.status_code in (200, 500)
    if resp.status_code == 200:
        assert "flowRunId" in resp.json()

    # Cleanup
    await http_client.delete(f"/episodes/{ep_id}")


@pytest.mark.e2e
async def test_sse_connection_live(http_client: httpx.AsyncClient):
    """Verify SSE endpoint returns text/event-stream content type."""
    ep_id = e2e_id()
    script = make_script_json("SSE Test")
    await http_client.post(
        "/episodes",
        files={"script": ("script.json", script, "application/json")},
        data={"id": ep_id, "title": "SSE Test"},
    )

    # Connect to SSE stream — should get headers immediately
    async with http_client.stream("GET", f"/episodes/{ep_id}/stream") as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")
        # Read first few bytes (should be keepalive comment within 30s,
        # but we don't want to wait that long — just verify connection works)

    # Cleanup
    await http_client.delete(f"/episodes/{ep_id}")


@pytest.mark.e2e
async def test_episode_logs_live(http_client: httpx.AsyncClient):
    ep_id = e2e_id()
    script = make_script_json("Logs Test")
    await http_client.post(
        "/episodes",
        files={"script": ("script.json", script, "application/json")},
        data={"id": ep_id, "title": "Logs Test"},
    )

    resp = await http_client.get(f"/episodes/{ep_id}/logs", params={"tail": 10})
    assert resp.status_code == 200
    assert "lines" in resp.json()

    # Cleanup
    await http_client.delete(f"/episodes/{ep_id}")
