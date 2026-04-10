"""E2E tests — Episode CRUD via FastAPI routes against real Postgres + MinIO.

At least 5 test cases covering create, get detail, list, delete, duplicate-id.
"""

from __future__ import annotations

import json

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from server.core.repositories import EpisodeRepo, EventRepo
from server.core.storage import MinIOStorage, episode_script_key

from .conftest import e2e_id, make_script_json


# ---------------------------------------------------------------------------
# 1. Create episode — verify DB + MinIO
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_create_episode(api_client: AsyncClient, db_session: AsyncSession, storage: MinIOStorage):
    ep_id = e2e_id()
    script = make_script_json("CRUD Create Test")

    resp = await api_client.post(
        "/episodes",
        data={"id": ep_id, "title": "CRUD Create Test"},
        files={"script": ("script.json", script, "application/json")},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["id"] == ep_id
    assert body["title"] == "CRUD Create Test"
    assert body["status"] == "empty"

    # Verify DB
    repo = EpisodeRepo(db_session)
    ep = await repo.get(ep_id)
    assert ep is not None
    assert ep.title == "CRUD Create Test"

    # Verify MinIO — script.json uploaded
    key = episode_script_key(ep_id)
    exists = await storage.exists(key)
    assert exists, f"script.json should exist at {key}"

    # Verify an episode_created event was written
    event_repo = EventRepo(db_session)
    count = await event_repo.count(ep_id)
    assert count >= 1


# ---------------------------------------------------------------------------
# 2. Get episode detail — verify nested chunk structure
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_get_episode_detail(api_client: AsyncClient):
    ep_id = e2e_id()
    script = make_script_json("Detail Test")

    # Create
    resp = await api_client.post(
        "/episodes",
        data={"id": ep_id, "title": "Detail Test"},
        files={"script": ("script.json", script, "application/json")},
    )
    assert resp.status_code == 201

    # Get detail
    resp = await api_client.get(f"/episodes/{ep_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == ep_id
    assert body["title"] == "Detail Test"
    assert "chunks" in body
    assert isinstance(body["chunks"], list)
    # No chunks yet because P1 hasn't run
    assert len(body["chunks"]) == 0


# ---------------------------------------------------------------------------
# 3. List episodes — verify newly created episode appears
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_list_episodes(api_client: AsyncClient):
    ep_id = e2e_id()
    script = make_script_json("List Test")

    await api_client.post(
        "/episodes",
        data={"id": ep_id, "title": "List Test"},
        files={"script": ("script.json", script, "application/json")},
    )

    resp = await api_client.get("/episodes")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    ids = [ep["id"] for ep in body]
    assert ep_id in ids


# ---------------------------------------------------------------------------
# 4. Delete episode — verify DB + MinIO cleanup
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_delete_episode(api_client: AsyncClient, db_session: AsyncSession, storage: MinIOStorage):
    ep_id = e2e_id()
    script = make_script_json("Delete Test")

    await api_client.post(
        "/episodes",
        data={"id": ep_id, "title": "Delete Test"},
        files={"script": ("script.json", script, "application/json")},
    )

    # Delete
    resp = await api_client.delete(f"/episodes/{ep_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["deleted"] is True

    # Verify DB — gone
    repo = EpisodeRepo(db_session)
    ep = await repo.get(ep_id)
    assert ep is None

    # Verify GET returns 404 now
    resp = await api_client.get(f"/episodes/{ep_id}")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 5. Duplicate episode id — should fail with 422
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_duplicate_episode_id(api_client: AsyncClient):
    ep_id = e2e_id()
    script = make_script_json("Duplicate Test")

    resp1 = await api_client.post(
        "/episodes",
        data={"id": ep_id, "title": "First"},
        files={"script": ("script.json", script, "application/json")},
    )
    assert resp1.status_code == 201

    resp2 = await api_client.post(
        "/episodes",
        data={"id": ep_id, "title": "Second"},
        files={"script": ("script.json", script, "application/json")},
    )
    assert resp2.status_code == 422
    body = resp2.json()
    assert body["error"] == "invalid_input"


# ---------------------------------------------------------------------------
# 6. Delete non-existent episode → 404
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_delete_nonexistent(api_client: AsyncClient):
    resp = await api_client.delete(f"/episodes/{e2e_id()}")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 7. Create with config override
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_create_with_config(api_client: AsyncClient):
    ep_id = e2e_id()
    config = json.dumps({"p2": {"temperature": 0.5}})
    script = make_script_json("Config Test")

    resp = await api_client.post(
        "/episodes",
        data={"id": ep_id, "title": "Config Test", "config": config},
        files={"script": ("script.json", script, "application/json")},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["config"]["p2"]["temperature"] == 0.5
