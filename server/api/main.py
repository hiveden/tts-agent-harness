"""FastAPI application entry point.

Lifespan:
- Startup: build DB engine, start asyncpg LISTEN connection for SSE.
- Shutdown: close LISTEN connection.

Middleware:
- CORS for localhost:3010 (Next.js dev).
- DomainError → HTTP status mapping.
- Shared-token auth (dev mode if HARNESS_API_TOKEN is unset).
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from server.api.auth import _Unauthorized, unauthorized_handler, verify_token
from server.api.errors import install_error_handlers
from server.api.routes.episodes import router as episodes_router
from server.api.routes.health import router as health_router
from server.api.sse import router as sse_router
from server.api.sse import start_listener, stop_listener


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Start SSE listener
    db_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://harness:harness@localhost:55432/harness",
    )
    await start_listener(db_url)
    yield
    await stop_listener()


app = FastAPI(
    title="TTS Agent Harness API",
    version="0.1.0",
    lifespan=lifespan,
    dependencies=[Depends(verify_token)],
)

# --- middleware ---

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3010",
        "http://127.0.0.1:3010",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- error handlers ---

install_error_handlers(app)
app.add_exception_handler(_Unauthorized, unauthorized_handler)  # type: ignore[arg-type]

# --- routers ---

app.include_router(episodes_router)
app.include_router(health_router)
app.include_router(sse_router)
