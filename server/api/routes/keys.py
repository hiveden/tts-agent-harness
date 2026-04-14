"""API-key management routes — store keys as encrypted httpOnly cookies."""

from __future__ import annotations

import os

import httpx
from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from server.core.crypto import decrypt_value, encrypt_value

router = APIRouter(tags=["keys"])

_COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "true").lower() != "false"
_COOKIE_MAX_AGE = 86400 * 365  # 1 year

FISH_VERIFY_URL = "https://api.fish.audio/wallet/self/api-credit"
GROQ_VERIFY_URL = "https://api.groq.com/openai/v1/models"


class KeysBody(BaseModel):
    fish_key: str | None = None
    groq_key: str | None = None


class KeysStatus(BaseModel):
    fish: bool
    groq: bool
    error: str | None = None


def _set_cookie(response: Response, name: str, value: str) -> None:
    response.set_cookie(
        key=name,
        value=encrypt_value(value),
        httponly=True,
        secure=_COOKIE_SECURE,
        samesite="strict",
        max_age=_COOKIE_MAX_AGE,
        path="/",
    )


async def _verify_fish(key: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(FISH_VERIFY_URL, headers={"Authorization": f"Bearer {key}"})
            return r.is_success
    except Exception:
        return False


async def _verify_groq(key: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(GROQ_VERIFY_URL, headers={"Authorization": f"Bearer {key}"})
            return r.is_success
    except Exception:
        return False


@router.post("/keys", response_model=KeysStatus)
async def save_keys(body: KeysBody, request: Request, response: Response) -> KeysStatus:
    errors: list[str] = []

    # Carry forward existing cookies for keys not being updated
    fish_ok = bool(request.cookies.get("__fish_key"))
    groq_ok = bool(request.cookies.get("__groq_key"))

    if body.fish_key:
        if await _verify_fish(body.fish_key):
            _set_cookie(response, "__fish_key", body.fish_key)
            fish_ok = True
        else:
            errors.append("Fish API Key 无效")

    if body.groq_key:
        if await _verify_groq(body.groq_key):
            _set_cookie(response, "__groq_key", body.groq_key)
            groq_ok = True
        else:
            errors.append("Groq API Key 无效")

    return KeysStatus(fish=fish_ok, groq=groq_ok, error="；".join(errors) if errors else None)


@router.get("/keys/status", response_model=KeysStatus)
async def keys_status(request: Request) -> KeysStatus:
    fish_ok = False
    enc = request.cookies.get("__fish_key")
    if enc:
        try:
            decrypt_value(enc)
            fish_ok = True
        except Exception:
            pass

    groq_ok = False
    enc = request.cookies.get("__groq_key")
    if enc:
        try:
            decrypt_value(enc)
            groq_ok = True
        except Exception:
            pass

    return KeysStatus(fish=fish_ok, groq=groq_ok)


@router.delete("/keys", response_model=KeysStatus)
async def delete_keys(response: Response) -> KeysStatus:
    response.delete_cookie("__fish_key", path="/", httponly=True, secure=_COOKIE_SECURE, samesite="strict")
    response.delete_cookie("__groq_key", path="/", httponly=True, secure=_COOKIE_SECURE, samesite="strict")
    return KeysStatus(fish=False, groq=False)
