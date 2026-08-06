"""Langfuse tracing, optional and non-fatal.

Every model call in the project already funnels through `llm.py`, so tracing
hooks in at one place. It is deliberately optional: without Langfuse keys the
functions here are no-ops, because a missing observability backend must never
stop someone studying. Failures inside tracing are swallowed for the same
reason — a broken trace should not take down a course that was generating fine.

Set LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY and optionally LANGFUSE_HOST to
turn it on.
"""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from typing import Any

_client: Any = None
_enabled: bool | None = None


def enabled() -> bool:
    """True when Langfuse is configured and importable."""
    global _client, _enabled
    if _enabled is not None:
        return _enabled

    if not (os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")):
        _enabled = False
        return False

    try:
        from langfuse import Langfuse

        _client = Langfuse(
            public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
            secret_key=os.environ["LANGFUSE_SECRET_KEY"],
            host=os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com"),
        )
        _enabled = True
    except Exception:  # noqa: BLE001
        # Wrong version, unreachable host, bad keys — none of it is worth
        # failing a course over.
        _enabled = False
    return _enabled


@contextmanager
def generation(
    *,
    name: str,
    model: str,
    prompt: str,
    metadata: dict | None = None,
):
    """Record one model call.

    Yields a dict the caller fills in with `output` and `usage`; both are
    optional, and anything left unset simply does not appear in the trace.
    """
    if not enabled():
        yield {}
        return

    started = time.time()
    result: dict[str, Any] = {}
    error: str | None = None
    try:
        yield result
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        try:
            usage = result.get("usage") or {}
            _client.create_generation(  # type: ignore[union-attr]
                name=name,
                model=model,
                input=prompt[:4000],
                output=str(result.get("output", ""))[:4000],
                usage_details={
                    "input": usage.get("input_tokens", 0),
                    "output": usage.get("output_tokens", 0),
                    "cache_read_input_tokens": usage.get("cache_read_tokens", 0),
                    "cache_creation_input_tokens": usage.get("cache_write_tokens", 0),
                },
                metadata={
                    **(metadata or {}),
                    "latency_s": round(time.time() - started, 2),
                    **({"error": error} if error else {}),
                },
                level="ERROR" if error else "DEFAULT",
            )
        except Exception:  # noqa: BLE001
            pass


def flush() -> None:
    """Send buffered events. Worth calling before a short-lived process exits."""
    if enabled():
        try:
            _client.flush()  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass
