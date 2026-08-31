"""Persisted course history so regenerated notes are not paid for twice.

A finished course is stored as JSON (modules, citations, quiz) keyed by a
trust-based user_id, the same isolation model as uploads, not real auth.
"""

from __future__ import annotations

import json
from typing import Any

from . import db
from .identity import normalize


GENERATION_STATUSES = frozenset({"generating", "complete", "partial"})


def ensure_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS courses (
            id                  BIGSERIAL PRIMARY KEY,
            user_id             TEXT NOT NULL DEFAULT '',
            goal                TEXT NOT NULL,
            summary             TEXT NOT NULL DEFAULT '',
            namespace           TEXT NOT NULL,
            module_titles       JSONB NOT NULL DEFAULT '[]',
            modules             JSONB NOT NULL DEFAULT '[]',
            estimated_cost_usd  DOUBLE PRECISION,
            with_quiz           BOOLEAN NOT NULL DEFAULT false,
            used_style          BOOLEAN NOT NULL DEFAULT false,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    # Added after the table shipped, so it is an ALTER rather than a column in
    # the CREATE above: existing rows keep their history.
    conn.execute(
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS progress JSONB NOT NULL DEFAULT '{}'"
    )
    conn.execute(
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS opened_at TIMESTAMPTZ"
    )
    # A clean title for the library, and the length of the whole course, so a
    # card can say how long it is without the client parsing every section.
    conn.execute("ALTER TABLE courses ADD COLUMN IF NOT EXISTS title TEXT")
    conn.execute(
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS word_count INT NOT NULL DEFAULT 0"
    )
    conn.execute(
        """
        ALTER TABLE courses
        ADD COLUMN IF NOT EXISTS generation_status TEXT NOT NULL DEFAULT 'complete'
        """
    )
    # Full planner output so a partial course can resume without re-planning.
    conn.execute(
        "ALTER TABLE courses ADD COLUMN IF NOT EXISTS syllabus JSONB"
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS courses_user_created_idx
            ON courses (user_id, created_at DESC)
        """
    )


def word_count_of(modules: list[dict[str, Any]]) -> int:
    """Words across every written section, the basis for a reading estimate."""
    total = 0
    for module in modules:
        body = ((module.get("notes") or {}).get("body")) or ""
        total += len(body.split())
    return total


def slim_notes(notes: dict[str, Any] | None) -> dict[str, Any] | None:
    """Persist notes without embedding full passage text.

    Chunk bodies already live in `chunks`; courses keep ids and join on read.
    """
    if not notes:
        return notes
    out = {k: v for k, v in notes.items() if k != "chunks"}
    chunk_list = notes.get("chunks") or []
    if chunk_list and not out.get("chunk_ids"):
        ids: list[int] = []
        for chunk in chunk_list:
            if isinstance(chunk, dict) and "id" in chunk:
                ids.append(int(chunk["id"]))
            elif hasattr(chunk, "id"):
                ids.append(int(chunk.id))
        out["chunk_ids"] = ids
    return out


def slim_modules(modules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**module, "notes": slim_notes(module.get("notes"))} for module in modules]


def hydrate_modules(modules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach chunk rows from Postgres for the UI / explain path.

    Legacy rows that still store full `chunks` in JSONB are left untouched.
    """
    needed: list[int] = []
    for module in modules:
        notes = module.get("notes") or {}
        if notes.get("chunks"):
            continue
        for key in ("chunk_ids", "cited_chunk_ids"):
            for cid in notes.get(key) or []:
                needed.append(int(cid))
    ordered_ids = list(dict.fromkeys(needed))
    if not ordered_ids:
        return modules

    with db.connect() as conn:
        rows = db.get_chunks_by_ids(conn, ordered_ids)
    by_id = {int(r["id"]): r for r in rows}

    hydrated: list[dict[str, Any]] = []
    for module in modules:
        notes = module.get("notes")
        if not notes or notes.get("chunks"):
            hydrated.append(module)
            continue
        order = notes.get("chunk_ids") or notes.get("cited_chunk_ids") or []
        chunks = []
        for cid in order:
            row = by_id.get(int(cid))
            if not row:
                continue
            chunks.append(
                {
                    "id": int(row["id"]),
                    "text": row["text"],
                    "document_title": row["document_title"],
                    "document_url": row["document_url"],
                    "score": float(row.get("score") or 0),
                }
            )
        hydrated.append({**module, "notes": {**notes, "chunks": chunks}})
    return hydrated


def save(
    *,
    user_id: str,
    goal: str,
    summary: str,
    title: str = "",
    namespace: str,
    module_titles: list[str],
    modules: list[dict[str, Any]],
    estimated_cost_usd: float | None,
    with_quiz: bool,
    used_style: bool,
    generation_status: str = "generating",
    syllabus: dict[str, Any] | None = None,
) -> int:
    status = _valid_status(generation_status)
    slimmed = slim_modules(modules)
    with db.connect() as conn:
        ensure_table(conn)
        row = conn.execute(
            """
            INSERT INTO courses (
                user_id, goal, summary, title, namespace, module_titles, modules,
                estimated_cost_usd, with_quiz, used_style, generation_status,
                syllabus, word_count
            )
            VALUES (
                %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s,
                %s::jsonb, %s
            )
            RETURNING id
            """,
            (
                normalize(user_id),
                goal,
                summary,
                title or None,
                namespace,
                json.dumps(module_titles),
                json.dumps(slimmed, default=str),
                estimated_cost_usd,
                with_quiz,
                used_style,
                status,
                json.dumps(syllabus) if syllabus is not None else None,
                word_count_of(slimmed),
            ),
        ).fetchone()
        conn.commit()
    return int(row["id"])


def update(
    course_id: int,
    *,
    summary: str | None = None,
    namespace: str | None = None,
    module_titles: list[str] | None = None,
    modules: list[dict[str, Any]] | None = None,
    estimated_cost_usd: float | None = None,
    generation_status: str | None = None,
    syllabus: dict[str, Any] | None = None,
    title: str | None = None,
) -> bool:
    """Patch a course in place as modules finish (or after a disconnect)."""
    fields: list[str] = []
    values: list[Any] = []
    if summary is not None:
        fields.append("summary = %s")
        values.append(summary)
    if namespace is not None:
        fields.append("namespace = %s")
        values.append(namespace)
    if module_titles is not None:
        fields.append("module_titles = %s::jsonb")
        values.append(json.dumps(module_titles))
    if modules is not None:
        slimmed = slim_modules(modules)
        fields.append("modules = %s::jsonb")
        values.append(json.dumps(slimmed, default=str))
        fields.append("word_count = %s")
        values.append(word_count_of(slimmed))
    if title is not None:
        fields.append("title = %s")
        values.append(title)
    if estimated_cost_usd is not None:
        fields.append("estimated_cost_usd = %s")
        values.append(estimated_cost_usd)
    if generation_status is not None:
        fields.append("generation_status = %s")
        values.append(_valid_status(generation_status))
    if syllabus is not None:
        fields.append("syllabus = %s::jsonb")
        values.append(json.dumps(syllabus))
    if not fields:
        return False
    values.append(course_id)
    with db.connect() as conn:
        ensure_table(conn)
        cur = conn.execute(
            f"UPDATE courses SET {', '.join(fields)} WHERE id = %s",
            values,
        )
        conn.commit()
        return cur.rowcount > 0


def set_generation_status(course_id: int, status: str) -> bool:
    return update(course_id, generation_status=status)


def abandon_stale_generating() -> int:
    """Mark in-flight courses as partial after a process restart.

    Generation jobs live in memory. Anything still `generating` when the API
    starts cannot still be writing, so leave History in an honest state.
    """
    with db.connect() as conn:
        ensure_table(conn)
        cur = conn.execute(
            """
            UPDATE courses
               SET generation_status = 'partial'
             WHERE generation_status = 'generating'
            """
        )
        conn.commit()
        return int(cur.rowcount)


def list_for_user(user_id: str, *, limit: int = 50) -> list[dict]:
    with db.connect() as conn:
        ensure_table(conn)
        rows = conn.execute(
            """
            SELECT id, user_id, goal, summary, title, namespace, module_titles,
                   estimated_cost_usd, with_quiz, used_style, created_at,
                   progress, opened_at, word_count, generation_status,
                   jsonb_array_length(COALESCE(module_titles, '[]'::jsonb))
                     AS planned_count,
                   jsonb_array_length(modules) AS module_count,
                   (
                     SELECT count(*)::int
                     FROM jsonb_array_elements(modules) AS m
                     WHERE COALESCE((m->'notes'->>'refused')::boolean, false) = false
                       AND COALESCE(m->>'error', '') = ''
                       AND length(trim(COALESCE(m->'notes'->>'body', ''))) > 0
                   ) AS usable_count
            FROM courses
            WHERE user_id = %s
            ORDER BY COALESCE(opened_at, created_at) DESC
            LIMIT %s
            """,
            (normalize(user_id), limit),
        ).fetchall()
    return [_summary_row(r) for r in rows]


def list_all(*, limit: int = 50) -> list[dict]:
    """Every saved course, newest first, regardless of user.

    The web UI scopes history to one browser profile, which is right there and
    wrong on the command line: someone exporting a course locally knows which
    course they mean but not which profile id it was saved under.
    """
    with db.connect() as conn:
        ensure_table(conn)
        rows = conn.execute(
            """
            SELECT id, user_id, goal, title, created_at, word_count,
                   generation_status,
                   jsonb_array_length(modules) AS module_count
            FROM courses
            ORDER BY COALESCE(opened_at, created_at) DESC
            LIMIT %s
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def claim(from_users: list[str], to_user: str) -> int:
    """Move courses from other trust-ids onto one identity.

    Browser profiles used to mint a new `reader-…` id when localStorage was
    cleared, which orphaned saved courses. Claiming reunites them.
    """
    dest = normalize(to_user)
    sources = sorted({normalize(u) for u in from_users if normalize(u) != dest})
    if not sources:
        return 0
    with db.connect() as conn:
        ensure_table(conn)
        cur = conn.execute(
            """
            UPDATE courses
               SET user_id = %s
             WHERE user_id = ANY(%s)
            """,
            (dest, sources),
        )
        conn.commit()
        return int(cur.rowcount)


def get(course_id: int) -> dict | None:
    with db.connect() as conn:
        ensure_table(conn)
        row = conn.execute(
            """
            SELECT id, user_id, goal, summary, title, namespace, module_titles,
                   modules, estimated_cost_usd, with_quiz, used_style,
                   created_at, progress, opened_at, word_count, generation_status, syllabus
            FROM courses
            WHERE id = %s
            """,
            (course_id,),
        ).fetchone()
    if not row:
        return None
    return _full_row(row, hydrate=True)


def delete(course_id: int, *, user_id: str | None = None) -> bool:
    with db.connect() as conn:
        ensure_table(conn)
        if user_id is None:
            cur = conn.execute("DELETE FROM courses WHERE id = %s", (course_id,))
        else:
            cur = conn.execute(
                "DELETE FROM courses WHERE id = %s AND user_id = %s",
                (course_id, normalize(user_id)),
            )
        conn.commit()
        return cur.rowcount > 0


def set_progress(course_id: int, progress: dict[str, Any]) -> dict | None:
    """Replace the stored progress blob: modules read, and the bookmark."""
    with db.connect() as conn:
        ensure_table(conn)
        row = conn.execute(
            """
            UPDATE courses
               SET progress = %s::jsonb, opened_at = now()
             WHERE id = %s
            RETURNING id, progress
            """,
            (json.dumps(progress), course_id),
        ).fetchone()
        conn.commit()
    if not row:
        return None
    return {"id": row["id"], "progress": _parse_json(row["progress"])}


def touch(course_id: int) -> None:
    """Record that a course was opened, so `continue studying` is accurate."""
    with db.connect() as conn:
        ensure_table(conn)
        conn.execute(
            "UPDATE courses SET opened_at = now() WHERE id = %s", (course_id,)
        )
        conn.commit()


def _progress_fields(row: dict) -> dict:
    progress = _parse_json(row.get("progress")) or {}
    opened = row.get("opened_at")
    return {
        "progress": progress,
        "opened_at": opened.isoformat() if hasattr(opened, "isoformat") else opened,
    }


def _parse_json(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


def _valid_status(status: str) -> str:
    if status not in GENERATION_STATUSES:
        raise ValueError(f"invalid generation_status: {status}")
    return status


def _summary_row(row: dict) -> dict:
    titles = _parse_json(row["module_titles"]) or []
    planned = int(row.get("planned_count") or len(titles) or 0)
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "goal": row["goal"],
        "summary": row["summary"],
        "title": row.get("title") or row["goal"],
        "word_count": row.get("word_count") or 0,
        "namespace": row["namespace"],
        "module_titles": titles,
        "module_count": row["module_count"],
        "planned_count": planned,
        "usable_count": int(row.get("usable_count") or 0),
        "estimated_cost_usd": row["estimated_cost_usd"],
        "with_quiz": row["with_quiz"],
        "used_style": row["used_style"],
        "generation_status": row.get("generation_status") or "complete",
        "created_at": row["created_at"].isoformat()
        if hasattr(row["created_at"], "isoformat")
        else row["created_at"],
        **_progress_fields(row),
    }


def _full_row(row: dict, *, hydrate: bool = False) -> dict:
    titles = _parse_json(row["module_titles"]) or []
    modules = _parse_json(row["modules"]) or []
    if hydrate:
        modules = hydrate_modules(modules)
    usable = sum(
        1
        for m in modules
        if not m.get("error")
        and (m.get("notes") or {}).get("body")
        and not (m.get("notes") or {}).get("refused")
    )
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "goal": row["goal"],
        "summary": row["summary"],
        "title": row.get("title") or row["goal"],
        "word_count": row.get("word_count") or 0,
        "namespace": row["namespace"],
        "module_titles": titles,
        "modules": modules,
        "module_count": len(modules),
        "planned_count": len(titles),
        "usable_count": usable,
        "estimated_cost_usd": row["estimated_cost_usd"],
        "with_quiz": row["with_quiz"],
        "used_style": row["used_style"],
        "generation_status": row.get("generation_status") or "complete",
        "syllabus": _parse_json(row.get("syllabus")),
        "created_at": row["created_at"].isoformat()
        if hasattr(row["created_at"], "isoformat")
        else row["created_at"],
        **_progress_fields(row),
    }
