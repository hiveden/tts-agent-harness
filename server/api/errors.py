"""Unified error handling — maps DomainError codes to HTTP status codes.

DomainError is the single exception type raised by core logic / Prefect tasks
on expected business failures.  This module installs a FastAPI exception handler
that translates each ``code`` to the appropriate HTTP status.

All error responses follow the shape:

    {"error": "<code>", "detail": "<message>"}
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from server.core.domain import DomainError

# --- code → HTTP status mapping -------------------------------------------

_STATUS_MAP: dict[str, int] = {
    "not_found": 404,
    "invalid_input": 422,
    "invalid_state": 409,
    "lock_busy": 423,
    "internal": 500,
}


def _status_for(code: str) -> int:
    return _STATUS_MAP.get(code, 500)


# --- handler ---------------------------------------------------------------


async def domain_error_handler(_request: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(
        status_code=_status_for(exc.code),
        content={"error": exc.code, "detail": exc.message},
    )


def install_error_handlers(app: FastAPI) -> None:
    """Register the DomainError exception handler on *app*."""
    app.add_exception_handler(DomainError, domain_error_handler)  # type: ignore[arg-type]
