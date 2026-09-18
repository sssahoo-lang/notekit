"""Real accounts: who someone is, rather than which browser they used.

Until now identity was a `reader-…` string the browser minted and sent with
every request. That is isolation between browsers, not authentication: whoever
holds the string is that reader, clearing storage lost the library, and no two
devices shared one. An account fixes all three.

What is stored, and what deliberately is not:

Passwords are never stored, and nor is anything a fast hash could reverse.
`hashlib.scrypt` derives a key that is memory-hard on purpose, so a leaked
table cannot be run through a GPU wordlist at speed. The parameters live in
the stored string, so raising them later does not invalidate existing
passwords: an old hash keeps verifying with the numbers it was made with.

Session tokens are stored as a SHA-256 digest, not as themselves. A digest is
the right tool here and a KDF is not: the token is already 256 bits of
randomness, so there is nothing to brute force, and a leaked session table
still cannot be replayed.

The session token reaches the browser as an httpOnly cookie, so page scripts
cannot read it. This app renders model output into the page, which is exactly
the situation where a token in localStorage becomes one XSS away from being
someone else's account.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timedelta, timezone

import psycopg

from . import db

# Cost parameters for new passwords. n is the memory/time knob: 2**15 blocks of
# 128 * r bytes is about 32 MB and a few tens of milliseconds, which is a fair
# trade for a login. Stored per hash, so this can be raised without a migration.
_SCRYPT_N = 2**15
_SCRYPT_R = 8
_SCRYPT_P = 1
_SALT_BYTES = 16
# OpenSSL refuses scrypt above 32 MB unless told otherwise, and n=2**15 with
# r=8 needs exactly that. Raising the ceiling keeps the cost parameters rather
# than quietly weakening them to fit a default.
_SCRYPT_MAXMEM = 128 * _SCRYPT_R * _SCRYPT_N * 2

SESSION_COOKIE = "notekit_session"
SESSION_DAYS = 30

# Deliberately loose. Address validation by regular expression is a well known
# way to reject real addresses; the only proof that an address works is mail
# sent to it, which this does not do.
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

MIN_PASSWORD = 10


class AccountError(ValueError):
    """Something the person can fix, phrased for them rather than for a log."""


def ensure_tables(conn: psycopg.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id            BIGSERIAL PRIMARY KEY,
            email         TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            display_name  TEXT NOT NULL DEFAULT '',
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY,
            user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at TIMESTAMPTZ NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS sessions_user_idx ON sessions (user_id)"
    )


# --- passwords ---------------------------------------------------------------


def hash_password(password: str) -> str:
    """Derive a verifier. The parameters travel with it, so they can change."""
    salt = os.urandom(_SALT_BYTES)
    key = hashlib.scrypt(
        password.encode(),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        maxmem=_SCRYPT_MAXMEM,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${key.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Check a password against a stored verifier, in constant time."""
    try:
        scheme, n, r, p, salt_hex, key_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        key = hashlib.scrypt(
            password.encode(),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            # From the stored parameters, so a hash made with older, cheaper
            # settings still verifies after the defaults above are raised.
            maxmem=128 * int(r) * int(n) * 2,
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(key.hex(), key_hex)


# --- accounts ----------------------------------------------------------------


def account_key(user_id: int) -> str:
    """The storage key a signed-in person's courses and uploads live under.

    Derived from the row id rather than the address, so changing an email
    later does not orphan a library.
    """
    return f"u{user_id}"


def _clean_email(email: str) -> str:
    value = (email or "").strip().lower()
    if not _EMAIL.match(value):
        raise AccountError("That does not look like an email address.")
    return value


def register(email: str, password: str, display_name: str = "") -> dict:
    """Create an account. Raises AccountError with something worth reading."""
    value = _clean_email(email)
    if len(password or "") < MIN_PASSWORD:
        raise AccountError(
            f"Use at least {MIN_PASSWORD} characters. A short phrase is easier "
            "to remember and harder to guess than a short word."
        )
    with db.connect() as conn:
        ensure_tables(conn)
        existing = conn.execute(
            "SELECT 1 FROM users WHERE email = %s", (value,)
        ).fetchone()
        if existing:
            raise AccountError("There is already an account with that address.")
        row = conn.execute(
            """
            INSERT INTO users (email, password_hash, display_name)
            VALUES (%s, %s, %s) RETURNING id, email, display_name
            """,
            (value, hash_password(password), (display_name or "").strip()),
        ).fetchone()
        conn.commit()
    return {"id": row["id"], "email": row["email"], "display_name": row["display_name"]}


def authenticate(email: str, password: str) -> dict | None:
    """Return the account, or None. Never says which half was wrong.

    An unknown address still pays for a hash, so the reply takes about as long
    either way and cannot be timed to enumerate who has an account.
    """
    value = (email or "").strip().lower()
    with db.connect() as conn:
        ensure_tables(conn)
        row = conn.execute(
            "SELECT id, email, display_name, password_hash FROM users WHERE email = %s",
            (value,),
        ).fetchone()
    if row is None:
        hash_password(password or "")
        return None
    if not verify_password(password or "", row["password_hash"]):
        return None
    return {
        "id": row["id"],
        "email": row["email"],
        "display_name": row["display_name"],
    }


def set_display_name(user_id: int, name: str) -> None:
    with db.connect() as conn:
        ensure_tables(conn)
        conn.execute(
            "UPDATE users SET display_name = %s WHERE id = %s",
            ((name or "").strip(), user_id),
        )
        conn.commit()


def change_password(user_id: int, current: str, new: str) -> None:
    if len(new or "") < MIN_PASSWORD:
        raise AccountError(f"Use at least {MIN_PASSWORD} characters.")
    with db.connect() as conn:
        ensure_tables(conn)
        row = conn.execute(
            "SELECT password_hash FROM users WHERE id = %s", (user_id,)
        ).fetchone()
        if row is None or not verify_password(current or "", row["password_hash"]):
            raise AccountError("That is not your current password.")
        conn.execute(
            "UPDATE users SET password_hash = %s WHERE id = %s",
            (hash_password(new), user_id),
        )
        # Every other session is signed out: a password change is what someone
        # does when they think another device should not still be signed in.
        conn.execute("DELETE FROM sessions WHERE user_id = %s", (user_id,))
        conn.commit()


# --- sessions ----------------------------------------------------------------


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def start_session(user_id: int) -> str:
    """Mint a session token. Only the digest is kept, so this is the one copy."""
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
    with db.connect() as conn:
        ensure_tables(conn)
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (%s, %s, %s)",
            (_digest(token), user_id, expires),
        )
        conn.execute("DELETE FROM sessions WHERE expires_at < now()")
        conn.commit()
    return token


def session_user(token: str | None) -> dict | None:
    """The account a token belongs to, or None if it is unknown or expired."""
    if not token:
        return None
    with db.connect() as conn:
        ensure_tables(conn)
        row = conn.execute(
            """
            SELECT u.id, u.email, u.display_name
            FROM sessions s JOIN users u ON u.id = s.user_id
            WHERE s.token_hash = %s AND s.expires_at > now()
            """,
            (_digest(token),),
        ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "email": row["email"],
        "display_name": row["display_name"],
    }


def end_session(token: str | None) -> None:
    if not token:
        return
    with db.connect() as conn:
        ensure_tables(conn)
        conn.execute("DELETE FROM sessions WHERE token_hash = %s", (_digest(token),))
        conn.commit()
