"""What a reader might mean, offered while they type.

A blank goal box is a blank-page problem, and "machine learning" is a subject
rather than a course. Two kinds of help, at two costs.

The instant kind is free: the reader's own courses and the subjects already
indexed on this instance, matched on what has been typed so far. Reopening a
course you built last week, or learning that "transformers" is already
gathered and would build at once, needs no model.

The related kind is one small model call: a few concrete goals a learner
typing this might actually mean, spanning levels and neighbouring subjects.
It runs after a pause rather than on every keystroke, is cached by what was
typed, and sits behind its own rate bucket, since a text box that spends a
fraction of a cent per pause is fine and one that spends it per key is not.
"""

from __future__ import annotations

from collections import OrderedDict

from pydantic import BaseModel, Field

from . import config, courses, db, llm
from .identity import normalize

_SYSTEM = """A learner is typing what they want to learn into a study tool that \
builds a short course from real sources. Given the partial text, suggest four \
concrete learning goals they might mean.

Each goal is a complete phrase a learner would type, such as "gradient descent \
from scratch" or "the CAP theorem for backend engineers", eight words or fewer. \
Span levels (one for a beginner, one assuming some background) and include one \
neighbouring subject they may not have thought of. Never repeat the input \
verbatim, never write questions, never number them."""


class _Suggestions(BaseModel):
    goals: list[str] = Field(description="Four concrete learning goals, each under nine words")


_cache: OrderedDict[str, list[str]] = OrderedDict()
_CACHE_SIZE = 256


def instant(query: str, user: str, *, limit: int = 5) -> dict:
    """Matches from the reader's own courses and the subjects already indexed."""
    q = " ".join(query.lower().split())
    if len(q) < 2:
        return {"history": [], "topics": []}

    own = []
    for row in courses.list_for_user(normalize(user)):
        label = (row.get("title") or row.get("goal") or "").strip()
        if q in label.lower() or q in (row.get("goal") or "").lower():
            own.append({"id": row["id"], "label": label})
        if len(own) >= limit:
            break

    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT slug, label FROM topics
            WHERE ingested_at IS NOT NULL
              AND (slug ILIKE %s OR coalesce(label, '') ILIKE %s)
            ORDER BY slug LIMIT %s
            """,
            (f"%{q.replace(' ', '-')}%", f"%{q}%", limit),
        ).fetchall()
    topics = [
        {"slug": r["slug"], "label": r["label"] or r["slug"].replace("-", " ")}
        for r in rows
    ]
    return {"history": own, "topics": topics}


def related(query: str) -> list[str]:
    """Four goals a learner typing this might mean. Cached by the text typed."""
    key = " ".join(query.lower().split())
    if len(key) < 3:
        return []
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    parsed = llm.parse(
        model=config.PLANNER_MODEL,
        system=_SYSTEM,
        prompt=f"Typed so far: {query.strip()}",
        max_tokens=200,
        schema=_Suggestions,
        purpose="suggest-goals",
    )
    goals = [g.strip() for g in parsed.goals if g.strip() and g.strip().lower() != key][:4]
    _cache[key] = goals
    if len(_cache) > _CACHE_SIZE:
        _cache.popitem(last=False)
    return goals
