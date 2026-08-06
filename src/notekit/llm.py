"""Claude client wrapper with per-run token accounting.

Every LLM call in the project goes through here so the CLI can report what a
course actually cost. Nothing else in the codebase imports `anthropic` directly.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from collections.abc import AsyncIterator
from typing import TypeVar

import anthropic
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

from . import config
from .models import Usage

_client = anthropic.Anthropic()

# Generation is I/O-bound, so the streaming path runs on the async client.
# Threads were measurably worse: four worker threads each parsing their own SSE
# stream is GIL-bound work, and their first tokens staggered by 6s where four
# coroutines on one event loop do not contend at all.
_aclient = anthropic.AsyncAnthropic()
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


def _content_blocks(prompt: str, cached_prefix: str | None) -> list[dict]:
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
    return content


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
    content = _content_blocks(prompt, cached_prefix)

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


async def astream_complete(
    *,
    model: str,
    system: str,
    prompt: str,
    max_tokens: int,
    cached_prefix: str | None = None,
) -> AsyncIterator[str]:
    """Yield text deltas as they arrive. Usage is recorded when the stream ends."""
    extra = {"thinking": config.GENERATION_THINKING} if config.GENERATION_THINKING else {}

    async with _aclient.messages.stream(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": _content_blocks(prompt, cached_prefix)}],
        **extra,
    ) as stream:
        async for text in stream.text_stream:
            yield text
        final = await stream.get_final_message()

    _record(model, final.usage)
    if final.stop_reason == "refusal":
        raise RuntimeError(f"Model declined the request: {final.stop_details}")


async def astream_text(
    *,
    model: str,
    system: str,
    prompt: str,
    max_tokens: int,
    cached_prefix: str | None = None,
) -> str:
    """Collect a plain completion. Same request shape as astream_complete, so a
    cached prefix written by that call is read rather than re-sent."""
    chunks: list[str] = []
    async for delta in astream_complete(
        model=model,
        system=system,
        prompt=prompt,
        max_tokens=max_tokens,
        cached_prefix=cached_prefix,
    ):
        chunks.append(delta)
    return "".join(chunks)


async def aparse(
    *,
    model: str,
    system: str,
    prompt: str,
    max_tokens: int,
    schema: type[T],
    cached_prefix: str | None = None,
) -> T:
    response = await _aclient.messages.parse(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": _content_blocks(prompt, cached_prefix)}],
        output_format=schema,
    )
    _record(model, response.usage)

    if response.parsed_output is None:
        raise RuntimeError(f"Structured output failed (stop_reason={response.stop_reason})")
    return response.parsed_output


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
    content = _content_blocks(prompt, cached_prefix)

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
