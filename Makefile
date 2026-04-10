#
# TTS Agent Harness — Makefile
#
# Usage:
#   make dev       — start docker infra (postgres + minio + prefect)
#   make serve     — start FastAPI + Next.js dev servers
#   make stop      — stop app servers
#   make down      — stop everything (docker + app)
#

SHELL := /bin/bash

# ---------------------------------------------------------------------------
# Port mapping (host ports — must match docker-compose)
# ---------------------------------------------------------------------------

PG_PORT    ?= 55432
MINIO_PORT ?= 59000
MINIO_CON  ?= 59001
PREFECT_PORT ?= 54200
API_PORT   ?= 8100
WEB_PORT   ?= 3010

# ---------------------------------------------------------------------------
# Derived URLs
# ---------------------------------------------------------------------------

DATABASE_URL := postgresql+asyncpg://harness:harness@localhost:$(PG_PORT)/harness
MINIO_ENDPOINT := localhost:$(MINIO_PORT)

# ---------------------------------------------------------------------------
# Docker compose
# ---------------------------------------------------------------------------

COMPOSE_FILE := docker/docker-compose.dev.yml
COMPOSE := docker compose -f $(COMPOSE_FILE) -p tts-harness

.PHONY: help dev down status logs migrate psql serve stop serve-api serve-web open

help:
	@echo "TTS Agent Harness"
	@echo ""
	@echo "  Infrastructure:"
	@echo "    make dev            start postgres + minio + prefect-server"
	@echo "    make down           stop docker stack"
	@echo "    make status         show container status"
	@echo "    make logs           tail docker logs"
	@echo "    make migrate        run alembic migrations"
	@echo "    make psql           open psql shell"
	@echo ""
	@echo "  Application:"
	@echo "    make serve          start FastAPI (:$(API_PORT)) + Next.js (:$(WEB_PORT))"
	@echo "    make serve-api      start FastAPI only"
	@echo "    make serve-web      start Next.js only"
	@echo "    make stop           stop app servers"
	@echo "    make open           open browser to localhost:$(WEB_PORT)"
	@echo ""
	@echo "  Testing:"
	@echo "    make test           run server unit + integration tests"
	@echo "    make test-e2e       run e2e tests (requires dev stack running)"
	@echo "    make test-live      run live HTTP e2e tests"
	@echo "    make test-all       run everything"
	@echo "    make tsc            TypeScript type check"
	@echo "    make gen-types      regenerate OpenAPI → TS types"
	@echo ""
	@echo "  Ports: PG=$(PG_PORT) MinIO=$(MINIO_PORT) Prefect=$(PREFECT_PORT) API=$(API_PORT) Web=$(WEB_PORT)"

# ---------------------------------------------------------------------------
# Docker infra
# ---------------------------------------------------------------------------

dev:
	@if [ ! -f docker/.env ]; then cp docker/.env.example docker/.env; echo "created docker/.env"; fi
	$(COMPOSE) up -d
	@echo ""
	@echo "Infrastructure running:"
	@echo "  Postgres   localhost:$(PG_PORT)"
	@echo "  MinIO      localhost:$(MINIO_PORT) (console: $(MINIO_CON))"
	@echo "  Prefect    localhost:$(PREFECT_PORT)"

down:
	$(COMPOSE) down
	@$(MAKE) stop 2>/dev/null || true

status:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs -f

migrate:
	DATABASE_URL="$(DATABASE_URL)" cd server && alembic upgrade head

psql:
	$(COMPOSE) exec postgres psql -U harness -d harness

# ---------------------------------------------------------------------------
# Application servers
# ---------------------------------------------------------------------------

# PID files for clean stop
API_PID := /tmp/tts-harness-api.pid
WEB_PID := /tmp/tts-harness-web.pid

serve: serve-api serve-web
	@echo ""
	@echo "╔══════════════════════════════════════════════╗"
	@echo "║  TTS Harness running                        ║"
	@echo "║                                             ║"
	@echo "║  Frontend:  http://localhost:$(WEB_PORT)          ║"
	@echo "║  API:       http://localhost:$(API_PORT)          ║"
	@echo "║  API docs:  http://localhost:$(API_PORT)/docs     ║"
	@echo "║  Prefect:   http://localhost:$(PREFECT_PORT)        ║"
	@echo "║                                             ║"
	@echo "║  Logs: tail -f /tmp/tts-harness-*.log       ║"
	@echo "║  Stop: make stop                            ║"
	@echo "╚══════════════════════════════════════════════╝"

serve-api:
	@# Kill existing if running
	@if [ -f $(API_PID) ] && kill -0 $$(cat $(API_PID)) 2>/dev/null; then \
		echo "API already running (pid $$(cat $(API_PID)))"; \
	else \
		echo "Starting FastAPI on :$(API_PORT)..."; \
		set -a && [ -f .env ] && . ./.env; set +a; \
		env \
			no_proxy="localhost,127.0.0.1" \
			NO_PROXY="localhost,127.0.0.1" \
			DATABASE_URL="$(DATABASE_URL)" \
			MINIO_ENDPOINT="$(MINIO_ENDPOINT)" \
			MINIO_ACCESS_KEY=minioadmin \
			MINIO_SECRET_KEY=minioadmin \
			MINIO_BUCKET=tts-harness \
			PREFECT_API_URL="http://localhost:$(PREFECT_PORT)/api" \
			NODE_USE_ENV_PROXY=1 \
			nohup .venv-server/bin/uvicorn server.api.main:app \
				--host 0.0.0.0 --port $(API_PORT) --log-level info \
				> /tmp/tts-harness-api.log 2>&1 & \
		echo $$! > $(API_PID); \
		sleep 2; \
		if curl -sf http://localhost:$(API_PORT)/healthz > /dev/null 2>&1; then \
			echo "  API ready at http://localhost:$(API_PORT)"; \
		else \
			echo "  API failed to start — check /tmp/tts-harness-api.log"; \
		fi \
	fi

serve-web:
	@if [ -f $(WEB_PID) ] && kill -0 $$(cat $(WEB_PID)) 2>/dev/null; then \
		echo "Web already running (pid $$(cat $(WEB_PID)))"; \
	else \
		echo "Starting Next.js on :$(WEB_PORT)..."; \
		cd web && NEXT_PUBLIC_API_URL=http://localhost:$(API_PORT) \
			nohup pnpm dev > /tmp/tts-harness-web.log 2>&1 & \
		echo $$! > $(WEB_PID); \
		sleep 5; \
		if curl -sf http://localhost:$(WEB_PORT) > /dev/null 2>&1; then \
			echo "  Web ready at http://localhost:$(WEB_PORT)"; \
		else \
			echo "  Web starting... check /tmp/tts-harness-web.log"; \
		fi \
	fi

stop:
	@if [ -f $(API_PID) ]; then \
		kill $$(cat $(API_PID)) 2>/dev/null && echo "API stopped" || echo "API not running"; \
		rm -f $(API_PID); \
	fi
	@if [ -f $(WEB_PID) ]; then \
		kill $$(cat $(WEB_PID)) 2>/dev/null && echo "Web stopped" || echo "Web not running"; \
		rm -f $(WEB_PID); \
	fi
	@# Clean up any orphaned processes
	@lsof -t -i :$(API_PORT) 2>/dev/null | xargs kill 2>/dev/null || true
	@lsof -t -i :$(WEB_PORT) 2>/dev/null | xargs kill 2>/dev/null || true

open:
	@open http://localhost:$(WEB_PORT) 2>/dev/null || xdg-open http://localhost:$(WEB_PORT) 2>/dev/null || echo "open http://localhost:$(WEB_PORT)"

# ---------------------------------------------------------------------------
# Testing
# ---------------------------------------------------------------------------

PYTEST := SKIP_DOCKER_TESTS=1 .venv-server/bin/python -m pytest

test:
	$(PYTEST) server/tests/ -q --ignore=server/tests/e2e

test-e2e:
	$(PYTEST) server/tests/e2e/ -q --ignore=server/tests/e2e/test_live_http.py

test-live:
	env -u HTTPS_PROXY -u HTTP_PROXY -u ALL_PROXY \
		$(PYTEST) server/tests/e2e/test_live_http.py -v

test-all:
	$(PYTEST) server/tests/ -q

tsc:
	cd web && npx tsc --noEmit

# ---------------------------------------------------------------------------
# Code generation
# ---------------------------------------------------------------------------

gen-types:
	@echo "Exporting OpenAPI schema..."
	@.venv-server/bin/python -c "\
		from server.api.main import app; import json; \
		with open('web/lib/gen/openapi.json','w') as f: json.dump(app.openapi(),f,indent=2,default=str); \
		print('  web/lib/gen/openapi.json')"
	@echo "Generating TypeScript types..."
	@cd web && npx openapi-typescript lib/gen/openapi.json -o lib/gen/openapi.d.ts
	@echo "Done. Run 'make tsc' to verify."
