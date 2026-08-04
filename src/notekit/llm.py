"""Claude client wrapper with per-run token accounting.

Every LLM call in the project goes through here so the CLI can report what a
course actually cost. Nothing else in the codebase imports `anthropic` directly.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from collections.abc import Iterator
from typing import TypeVar

import anthropic
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

from . import config
from .models import Usage

_client = anthropic.Anthropic()
_lock = threading.Lock()
_usage: dict[str, Usage] = defaultdict(lambda: Usage(model="unknown"))


def _record(model: str, usage) -> None:
    with _lock:
        entry = _usage.setdefault(model, Usage(model=model))
        entry.input_tokens += usage.input_tokens
        entry.output_tokens += usage.output_tokens
        entry.cache_read_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0
        entry.cache_write_tokens += getattr(usage, "cache_creation_input_tokens", 0) or 0


def reset_usage() -> None:
    with _lock:
        _usage.clear()


def usage_report() -> tuple[list[Usage], float]:
    """Returns per-model usage and an estimated USD total."""
    with _lock:
        entries = list(_usage.values())
    total = 0.0
    for e in entries:
        rate_in, rate_out = config.PRICING.get(e.model, (0.0, 0.0))
        billed_in = e.input_tokens + e.cache_write_tokens * 1.25 + e.cache_read_tokens * 0.1
        total += billed_in * rate_in / 1e6 + e.output_tokens * rate_out / 1e6
    return entries, total


def complete(
    *,
    model: str,
    system: str,
    prompt: str,
    max_tokens: int,
    cached_prefix: str | None = None,
) -> str:
    """A plain text completion.

    `cached_prefix` is content shared across calls in the same module (the
    retrieved passages). Marking it cacheable means the quiz call re-reads it at
    a tenth of the input price instead of paying for it twice.
    """
    content: list[dict] = []
    if cached_prefix:
        content.append(
            {
                "type": "text",
                "text": cached_prefix,
                "cache_control": {"type": "ephemeral"},
            }
        )
    content.append({"type": "text", "text": prompt})

    response = _client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": content}],
    )
    _record(model, response.usage)

    if response.stop_reason == "refusal":
        raise RuntimeError(f"Model declined the request: {response.stop_details}")

    return "".join(b.text for b in response.content if b.type == "text")


def stream_complete(
    *,
    model: str,
    system: str,
    prompt: str,
    max_tokens: int,
    cached_prefix: str | None = None,
) -> Iterator[str]:
    """Yield text deltas as they arrive. Usage is recorded when the stream ends."""
    content: list[dict] = []
    if cached_prefix:
        content.append(
            {
                "type": "text",
                "text": cached_prefix,
                "cache_control": {"type": "ephemeral"},
            }
        )
    content.append({"type": "text", "text": prompt})

    extra = {"thinking": config.GENERATION_THINKING} if config.GENERATION_THINKING else {}

    with _client.messages.stream(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": content}],
        **extra,
    ) as stream:
        yield from stream.text_stream
        final = stream.get_final_message()

    _record(model, final.usage)
    if final.stop_reason == "refusal":
        raise RuntimeError(f"Model declined the request: {final.stop_details}")


def parse(
    *,
    model: str,
    system: str,
    prompt: str,
    max_tokens: int,
    schema: type[T],
    cached_prefix: str | None = None,
) -> T:
    """A completion constrained to a pydantic schema."""
    content: list[dict] = []
    if cached_prefix:
        content.append(
            {
                "type": "text",
                "text": cached_prefix,
                "cache_control": {"type": "ephemeral"},
            }
        )
    content.append({"type": "text", "text": prompt})

    response = _client.messages.parse(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": content}],
        output_format=schema,
    )
    _record(model, response.usage)

    if response.parsed_output is None:
        raise RuntimeError(f"Structured output failed (stop_reason={response.stop_reason})")
    return response.parsed_output
