# Dev Setup — TTS Agent Harness (W0 Infra)

This guide covers the **W0 infrastructure wave**: bringing up Postgres,
MinIO, and Prefect server on a clean laptop, then running the initial
alembic migration so the business schema is in place.

FastAPI, Prefect worker, whisperx-svc, and the Next.js UI land in later
waves and are not covered here.

## Prerequisites

| Tool            | Version    | Notes                                   |
|-----------------|------------|-----------------------------------------|
| Docker Desktop  | 24+        | Required for compose V2 (`docker compose`) |
| Python          | 3.12+      | Host-side alembic migrate               |
| GNU Make        | any        | Targets defined in `Makefile`           |
| `uv` or `pip`   | latest     | To install server dependencies          |

## Port map

| Port | Service        | Notes                                     |
|------|----------------|-------------------------------------------|
| 3010 | next-ui        | reserved (added by A10-Frontend wave)     |
| 8000 | fastapi        | reserved (added by A9-API wave)           |
| 4200 | prefect-server | Prefect UI + API                          |
| 5432 | postgres       | business + prefect databases              |
| 9000 | minio          | S3-compatible API                          |
| 9001 | minio-console  | web UI (user: `minioadmin` / `minioadmin`) |
| 7860 | whisperx-svc   | reserved (added by A3-WhisperX wave)      |

## First run

```bash
# 1) Create docker/.env from the example template
make env

# 2) Start postgres + minio + prefect-server (detached)
make dev

# 3) Wait ~20s for health checks, then verify
make status
```

Expected `make status` output: all services `running (healthy)` except
`minio-init` which exits `0` after creating the `tts-harness` bucket.

## Install server deps + run migration

```bash
# Create a venv and install (pick one)
python -m venv .venv && source .venv/bin/activate
pip install -e 'server[dev]'

# Apply the initial schema to the business database on localhost:5432
make migrate
```

Expected: alembic reports `Running upgrade  -> V001_initial, V001 initial`
and exits 0.

## Verify the stack

### Postgres — 5 business tables present

```bash
make psql
# then at the psql prompt:
\dt
```

You should see: `alembic_version`, `chunks`, `episodes`, `events`,
`stage_runs`, `takes`.

### MinIO — bucket exists

```bash
make minio-console   # opens http://localhost:9001
```

Log in with `minioadmin` / `minioadmin`. The `tts-harness` bucket is
listed in the Object Browser.

### Prefect UI

```bash
open http://localhost:4200
```

You land on an empty Prefect dashboard. No deployments yet — A8-Flow
registers them in a later wave.

## Tear down

```bash
make down              # stop containers, keep volumes
# nuke volumes too (destroys all DB + MinIO data):
docker volume rm tts-harness-postgres-data tts-harness-minio-data tts-harness-prefect-data
```

## Troubleshooting

- **`make dev` hangs on prefect-server healthcheck**: prefect server needs
  ~30s to apply its own internal migrations on first boot. `make logs`
  will show progress. Retry `make status` after ~60s.
- **`make migrate` fails with `connection refused`**: `make dev` must be
  running first. Check `make status`.
- **`minio-init` exits with error**: remove the stopped container and
  re-run `make dev`. The bucket creation is idempotent.
