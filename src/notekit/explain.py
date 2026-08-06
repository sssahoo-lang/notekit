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

You are given the source passages those notes were written from, the sentence \
or paragraph the reader highlighted, and optionally their question.

Rules:

1. Answer only from the source passages. If they do not cover what the reader \
asks, say plainly which part is missing — never fill the gap from your own \
knowledge.
2. Cite every supporting passage inline as [c123], using only the ids given.
3. Be direct and short: a few sentences. Untangle the hard idea; do not \
re-teach the whole module.
4. Do not quote the highlighted text back before answering.
5. If style guidance appears in the user turn, it changes phrasing only — it \
does not license new facts."""


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

    Prefer hydrated `notes.chunks`; fall back to loading ids from Postgres when
    a course was stored in the slim form (ids only).
    """
    modules = course.get("modules") or []
    match = next(
        (m for m in modules if int(m.get("index", -1)) == module_index), None
    )
    if not match:
        return "", False

    notes = match.get("notes") or {}
    chunks = list(notes.get("chunks") or [])
    if not chunks:
        ids = list(notes.get("chunk_ids") or notes.get("cited_chunk_ids") or [])
        if ids:
            from . import db

            with db.connect() as conn:
                chunks = db.get_chunks_by_ids(conn, [int(i) for i in ids])
    if not chunks:
        return "", False

    block = "\n\n".join(
        f"[c{c['id']}] (from: {c.get('document_title', 'source')})\n{c['text']}"
        for c in chunks
    )
    return f"Source passages:\n\n{block}", True
