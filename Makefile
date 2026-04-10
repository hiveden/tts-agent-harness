#
# TTS Agent Harness — Makefile
#
# 所有配置从根 .env 读取，不在此文件 hardcode。
# 切环境: cp .env.dev .env / cp .env.prod .env
#

SHELL := /bin/bash

# Load .env into make's env
-include .env
export

# Defaults (fallback if .env missing)
API_PORT      ?= 8100
WEB_PORT      ?= 3010
POSTGRES_PORT ?= 55432
MINIO_API_PORT ?= 59000
MINIO_CONSOLE_PORT ?= 59001
PREFECT_PORT  ?= 54200
LOG_LEVEL     ?= info
WHISPERX_MODE ?= local

# Docker compose
COMPOSE := docker compose --env-file .env -f docker/docker-compose.dev.yml -p tts-harness

# PID files
API_PID      := /tmp/tts-harness-api.pid
WEB_PID      := /tmp/tts-harness-web.pid
WHISPERX_PID := /tmp/tts-harness-whisperx.pid

.PHONY: help env-dev env-prod env-test dev down status logs migrate psql \
        serve serve-api serve-web serve-whisperx stop open \
        test test-e2e test-e2e-browser test-live test-all tsc gen-types

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------

help:
	@echo "TTS Agent Harness"
	@echo ""
	@echo "  Environment:                             Ports:"
	@echo "    make env-dev     switch to dev            PG=$(POSTGRES_PORT) MinIO=$(MINIO_API_PORT)"
	@echo "    make env-prod    switch to prod           Prefect=$(PREFECT_PORT)"
	@echo "    make env-test    switch to test            API=$(API_PORT) Web=$(WEB_PORT)"
	@echo ""
	@echo "  Infrastructure:"
	@echo "    make dev         start docker stack"
	@echo "    make down        stop docker stack"
	@echo "    make status      container status"
	@echo "    make logs        tail docker logs"
	@echo "    make migrate     alembic upgrade head"
	@echo ""
	@echo "  Application:"
	@echo "    make serve       start all (api + web + whisperx)"
	@echo "    make stop        stop all app servers"
	@echo "    make open        open browser"
	@echo ""
	@echo "  Testing:"
	@echo "    make test            server unit + integration"
	@echo "    make test-e2e        e2e (ASGI transport)"
	@echo "    make test-e2e-browser  Playwright browser e2e"
	@echo "    make test-all        everything"
	@echo "    make tsc             TypeScript check"
	@echo "    make gen-types       regenerate OpenAPI → TS"

# ---------------------------------------------------------------------------
# Environment switching
# ---------------------------------------------------------------------------

env-dev:
	@cp .env.dev .env && echo "✓ switched to dev"

env-prod:
	@cp .env.prod .env && echo "✓ switched to prod — edit .env to fill secrets"

env-test:
	@cp .env.test .env && echo "✓ switched to test"

# ---------------------------------------------------------------------------
# Docker infrastructure
# ---------------------------------------------------------------------------

dev:
	@if [ ! -f .env ]; then cp .env.dev .env; echo "created .env from .env.dev"; fi
	$(COMPOSE) up -d
	@echo ""
	@echo "Infrastructure: PG=:$(POSTGRES_PORT) MinIO=:$(MINIO_API_PORT) Prefect=:$(PREFECT_PORT)"

down:
	$(COMPOSE) down
	@$(MAKE) stop 2>/dev/null || true

status:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs -f

migrate:
	cd server && alembic upgrade head

psql:
	$(COMPOSE) exec postgres psql -U harness -d harness

# ---------------------------------------------------------------------------
# Application servers
# ---------------------------------------------------------------------------

serve: serve-api serve-web serve-whisperx
	@echo ""
	@echo "╔══════════════════════════════════════════════╗"
	@echo "║  TTS Harness running                        ║"
	@echo "║                                             ║"
	@echo "║  Frontend:  http://localhost:$(WEB_PORT)          ║"
	@echo "║  API:       http://localhost:$(API_PORT)          ║"
	@echo "║  API docs:  http://localhost:$(API_PORT)/docs     ║"
	@echo "║  WhisperX:  http://localhost:7860            ║"
	@echo "║  Prefect:   http://localhost:$(PREFECT_PORT)        ║"
	@echo "║                                             ║"
	@echo "║  Logs: tail -f /tmp/tts-harness-*.log       ║"
	@echo "║  Stop: make stop                            ║"
	@echo "╚══════════════════════════════════════════════╝"

serve-api:
	@if [ -f $(API_PID) ] && kill -0 $$(cat $(API_PID)) 2>/dev/null; then \
		echo "API already running (pid $$(cat $(API_PID)))"; \
	else \
		echo "Starting FastAPI on :$(API_PORT)..."; \
		set -a && . ./.env 2>/dev/null; set +a; \
		NO_PROXY="localhost,127.0.0.1" \
			nohup .venv-server/bin/uvicorn server.api.main:app \
				--host 0.0.0.0 --port $(API_PORT) --log-level $(LOG_LEVEL) \
				> /tmp/tts-harness-api.log 2>&1 & \
		echo $$! > $(API_PID); \
		sleep 2; \
		if curl -sf --noproxy '*' http://localhost:$(API_PORT)/healthz > /dev/null 2>&1; then \
			echo "  API ready at http://localhost:$(API_PORT)"; \
		else \
			echo "  API failed — check /tmp/tts-harness-api.log"; \
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
		if curl -sf --noproxy '*' http://localhost:$(WEB_PORT) > /dev/null 2>&1; then \
			echo "  Web ready at http://localhost:$(WEB_PORT)"; \
		else \
			echo "  Web starting... check /tmp/tts-harness-web.log"; \
		fi \
	fi

serve-whisperx:
	@if [ -f $(WHISPERX_PID) ] && kill -0 $$(cat $(WHISPERX_PID)) 2>/dev/null; then \
		echo "WhisperX already running (pid $$(cat $(WHISPERX_PID)))"; \
	elif [ "$(WHISPERX_MODE)" = "docker" ]; then \
		echo "Starting WhisperX (Docker)..."; \
		docker rm -f whisperx-svc 2>/dev/null; \
		docker run -d --name whisperx-svc \
			-p 7860:7860 \
			-v whisperx-models:/models \
			-e WHISPER_MODEL=large-v3 \
			-e WHISPER_DEVICE=cpu \
			whisperx-svc:dev; \
		echo "  WhisperX container started (model loading ~30-60s)"; \
	else \
		echo "Starting WhisperX (local .venv)..."; \
		MODEL_CACHE_DIR="$$HOME/.cache/huggingface/hub" \
		HF_HOME="$$HOME/.cache/huggingface" \
		nohup .venv/bin/uvicorn whisperx-svc.server:app \
			--host 0.0.0.0 --port 7860 --log-level $(LOG_LEVEL) \
			> /tmp/tts-harness-whisperx.log 2>&1 & \
		echo $$! > $(WHISPERX_PID); \
		echo "  WhisperX starting on :7860 (model loading ~30-60s)"; \
		echo "  Log: /tmp/tts-harness-whisperx.log"; \
	fi

stop:
	@for name_pid in "API:$(API_PID)" "Web:$(WEB_PID)" "WhisperX:$(WHISPERX_PID)"; do \
		name=$${name_pid%%:*}; pidfile=$${name_pid#*:}; \
		if [ -f "$$pidfile" ]; then \
			kill $$(cat "$$pidfile") 2>/dev/null && echo "$$name stopped" || echo "$$name not running"; \
			rm -f "$$pidfile"; \
		fi; \
	done
	@docker rm -f whisperx-svc 2>/dev/null && echo "WhisperX container stopped" || true
	@lsof -t -i :$(API_PORT) 2>/dev/null | xargs kill 2>/dev/null || true
	@lsof -t -i :$(WEB_PORT) 2>/dev/null | xargs kill 2>/dev/null || true

open:
	@open http://localhost:$(WEB_PORT) 2>/dev/null || echo "open http://localhost:$(WEB_PORT)"

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

test-e2e-browser:
	@curl -sf --noproxy '*' http://localhost:$(API_PORT)/healthz > /dev/null 2>&1 || (echo "API not running. Run: make serve" && exit 1)
	@curl -sf --noproxy '*' http://localhost:$(WEB_PORT) > /dev/null 2>&1 || (echo "Web not running. Run: make serve" && exit 1)
	cd web && pnpm exec playwright test

test-all: test test-e2e
	@echo "All server tests passed"

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
