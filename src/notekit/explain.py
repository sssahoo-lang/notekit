"""Answering "what does this mean?" about a passage of generated notes.

A reader who highlights a sentence they find hard gets an explanation drawn from
the same source passages the notes were written from — never from the model's
own knowledge. Personalised, easier phrasing must not become a licence to
invent: the grounding rule that governs the notes governs this too.

The passages are already stored alongside each saved module, so this costs one
cheap call and no retrieval.
"""

from __future__ import annotations

from . import config, llm
from .style import StyleProfile

_SYSTEM = """You explain a passage of study notes to the reader who wrote them.

You are given the source passages the notes were written from, the sentence or \
paragraph the reader highlighted, and optionally their question.

Rules:

1. Explain only what the source passages support. If they do not answer the \
reader's question, say plainly which part is not covered rather than filling \
the gap from your own knowledge.
2. Cite the passages you rely on inline as [c123], using the exact ids given.
3. Be direct and short — a few sentences. The reader is stuck on one specific \
thing, not asking for the module again.
4. Do not repeat the highlighted text back to them before answering."""


def explain(
    *,
    passages: str,
    highlighted: str,
    question: str | None = None,
    style: StyleProfile | None = None,
) -> str:
    """Explain a highlighted span, grounded in the module's own passages."""
    if not highlighted.strip():
        raise ValueError("Nothing highlighted to explain.")

    ask = (
        f"Their question: {question.strip()}"
        if question and question.strip()
        else "They did not ask anything specific — they marked this as hard to follow."
    )
    style_instruction = f"\n\n{style.as_instruction()}" if style else ""

    return llm.complete(
        model=config.EXPLAIN_MODEL,
        system=_SYSTEM,
        cached_prefix=passages,
        prompt=(
            f"The reader highlighted:\n\n{highlighted.strip()}\n\n{ask}"
            f"{style_instruction}"
        ),
        max_tokens=config.MAX_TOKENS_EXPLAIN,
    )


def passages_for_module(course: dict, module_index: int) -> tuple[str, bool]:
    """Rebuild the passage block for a saved module.

    Returns the block and whether any passages were found — a refused module has
    retrieved chunks but no notes, and is still worth explaining from.
    """
    modules = course.get("modules") or []
    match = next(
        (m for m in modules if int(m.get("index", -1)) == module_index), None
    )
    if not match:
        return "", False

    chunks = ((match.get("notes") or {}).get("chunks")) or []
    if not chunks:
        return "", False

    block = "\n\n".join(
        f"[c{c['id']}] (from: {c.get('document_title', 'source')})\n{c['text']}"
        for c in chunks
    )
    return f"Source passages:\n\n{block}", True
