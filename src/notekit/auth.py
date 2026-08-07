"""A shared password gate for the deployed demo.

This is a lock on the front door, not authentication. Everyone who gets in
shares one identity, so the per-user namespaces behind it are isolation between
browsers, not between people — someone who is inside and knows another
browser's profile id can still read its material. Real auth means sessions and
a user id derived from them, and is deliberately not what this is.

What it does buy: the deployed instance is not open to the whole internet, which
is the difference between "a demo you can show" and "an upload form anyone can
fill".

Off unless SITE_PASSWORD is set, so local development is unaffected.
"""

from __future__ import annotations

import hmac
import os
from hashlib import sha256

# Endpoints reachable without the password. Health must stay open or the
# platform's health check fails and the service is restarted forever.
OPEN_PATHS = {"/api/health", "/api/auth", "/docs", "/openapi.json", "/redoc"}

HEADER = "X-Site-Token"


def password() -> str | None:
    value = os.environ.get("SITE_PASSWORD", "").strip()
    return value or None


def enabled() -> bool:
    return password() is not None


def token_for(candidate: str) -> str:
    """A deterministic token derived from the password.

    Deterministic on purpose: no session store, no expiry to manage, and the
    server can verify without remembering anything. The trade-off is that the
    token cannot be revoked without changing the password, which is acceptable
    for a demo gate and would not be for real auth.
    """
    return hmac.new(
        candidate.encode(), b"notekit-site-access", sha256
    ).hexdigest()


def check_password(candidate: str) -> bool:
    expected = password()
    if expected is None:
        return True
    # compare_digest so a wrong guess takes the same time as a right one.
    return hmac.compare_digest(candidate.strip(), expected)


def check_token(candidate: str | None) -> bool:
    expected = password()
    if expected is None:
        return True
    if not candidate:
        return False
    return hmac.compare_digest(candidate, token_for(expected))
