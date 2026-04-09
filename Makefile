#
# TTS Agent Harness — Makefile
#
# Only targets relevant to the W0 infra wave are defined here. Later waves
# will add targets for running FastAPI, prefect worker, etc.
#

SHELL := /bin/bash

# Load docker/.env into make's env so the targets below pick up the right
# credentials. If docker/.env doesn't exist yet, copy from .env.example.
COMPOSE_FILE := docker/docker-compose.dev.yml
COMPOSE := docker compose --env-file docker/.env -f $(COMPOSE_FILE)

# Postgres connection params for `make psql` (host-side alembic / psql).
POSTGRES_USER ?= harness
POSTGRES_DB   ?= harness
POSTGRES_PORT ?= 5432

# Default DATABASE_URL for `make migrate` if not exported in the shell.
export DATABASE_URL ?= postgresql+asyncpg://$(POSTGRES_USER):harness@localhost:$(POSTGRES_PORT)/$(POSTGRES_DB)

.PHONY: help dev down migrate psql minio-console logs env status ps

help:
	@echo "TTS Harness — W0 dev targets"
	@echo ""
	@echo "  make env            create docker/.env from .env.example if missing"
	@echo "  make dev            start postgres + minio + prefect-server (detached)"
	@echo "  make down           stop the stack"
	@echo "  make status         docker compose ps"
	@echo "  make logs           tail logs for all services"
	@echo "  make migrate        alembic upgrade head (host-side, against localhost)"
	@echo "  make psql           open a psql shell inside the postgres container"
	@echo "  make minio-console  open MinIO web console"
	@echo ""

env:
	@if [ ! -f docker/.env ]; then \
		cp docker/.env.example docker/.env; \
		echo "created docker/.env from .env.example — edit secrets before prod"; \
	else \
		echo "docker/.env already exists"; \
	fi

dev: env
	$(COMPOSE) up -d
	@echo ""
	@echo "services starting — run 'make status' to check health"
	@echo "  postgres        localhost:$(POSTGRES_PORT)"
	@echo "  minio api       localhost:9000"
	@echo "  minio console   localhost:9001  (user: minioadmin / pass: minioadmin)"
	@echo "  prefect ui      localhost:4200"

down:
	$(COMPOSE) down

status ps:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs -f

migrate:
	cd server && alembic upgrade head

psql:
	$(COMPOSE) exec postgres psql -U $(POSTGRES_USER) -d $(POSTGRES_DB)

minio-console:
	@if command -v open >/dev/null 2>&1; then \
		open http://localhost:9001; \
	elif command -v xdg-open >/dev/null 2>&1; then \
		xdg-open http://localhost:9001; \
	else \
		echo "open http://localhost:9001 in your browser"; \
	fi
