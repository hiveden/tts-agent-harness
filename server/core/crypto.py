"""Symmetric encryption helpers for cookie values (Fernet)."""

from __future__ import annotations

import base64
import hashlib
import logging
import os

from cryptography.fernet import Fernet

_KEY_ENV = "COOKIE_SECRET"


def _derive_key() -> bytes:
    """Return a valid Fernet key (32-byte url-safe base64).

    If COOKIE_SECRET is already a valid Fernet key, use it directly.
    Otherwise derive one via SHA-256.  If unset, generate a random key
    (fine for single-process dev; keys won't survive restarts).
    """
    raw = os.environ.get(_KEY_ENV, "")
    if not raw:
        logging.warning("COOKIE_SECRET not set — using random key, cookies will not survive restarts")
        return Fernet.generate_key()
    # Try to use as-is (valid Fernet key = 44-char base64 of 32 bytes)
    try:
        Fernet(raw.encode())
        return raw.encode()
    except Exception:
        pass
    digest = hashlib.sha256(raw.encode()).digest()
    return base64.urlsafe_b64encode(digest)


_fernet = Fernet(_derive_key())


def encrypt_value(plain: str) -> str:
    return _fernet.encrypt(plain.encode()).decode()


def decrypt_value(token: str) -> str:
    return _fernet.decrypt(token.encode()).decode()
