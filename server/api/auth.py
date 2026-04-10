"""Shared-token authentication.

Behaviour:
- If ``HARNESS_API_TOKEN`` env var is **not set** → dev mode, all requests pass.
- If set → every request must carry ``Authorization: Bearer <token>`` with the
  matching value.  Mismatch → 401 ``{"error": "unauthorized", "detail": "..."}``.
"""

from __future__ import annotations

import os

from fastapi import Request
from fastapi.responses import JSONResponse


def _configured_token() -> str | None:
    return os.environ.get("HARNESS_API_TOKEN") or None


async def verify_token(request: Request) -> None:
    """FastAPI dependency — call via ``Depends(verify_token)``."""
    expected = _configured_token()
    if expected is None:
        # Dev mode — no auth required.
        return

    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise _unauthorized("missing or malformed Authorization header")

    token = auth_header[len("Bearer "):]
    if token != expected:
        raise _unauthorized("invalid token")


class _Unauthorized(Exception):
    """Internal sentinel — caught by the middleware installed in main.py."""

    def __init__(self, detail: str) -> None:
        self.detail = detail


def _unauthorized(detail: str) -> _Unauthorized:
    return _Unauthorized(detail)


async def unauthorized_handler(_request: Request, exc: _Unauthorized) -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={"error": "unauthorized", "detail": exc.detail},
    )
