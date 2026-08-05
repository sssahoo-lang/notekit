"""Persisted course history so regenerated notes are not paid for twice.

A finished course is stored as JSON (modules, citations, quiz) keyed by a
trust-based user_id — the same isolation model as uploads, not real auth.
"""

from __future__ import annotations

import json
from typing import Any

from . import db
from .identity import normalize


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
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS courses_user_created_idx
            ON courses (user_id, created_at DESC)
        """
    )


def save(
    *,
    user_id: str,
    goal: str,
    summary: str,
    namespace: str,
    module_titles: list[str],
    modules: list[dict[str, Any]],
    estimated_cost_usd: float | None,
    with_quiz: bool,
    used_style: bool,
) -> int:
    with db.connect() as conn:
        ensure_table(conn)
        row = conn.execute(
            """
            INSERT INTO courses (
                user_id, goal, summary, namespace, module_titles, modules,
                estimated_cost_usd, with_quiz, used_style
            )
            VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s)
            RETURNING id
            """,
            (
                normalize(user_id),
                goal,
                summary,
                namespace,
                json.dumps(module_titles),
                json.dumps(modules, default=str),
                estimated_cost_usd,
                with_quiz,
                used_style,
            ),
        ).fetchone()
        conn.commit()
    return int(row["id"])


def list_for_user(user_id: str, *, limit: int = 50) -> list[dict]:
    with db.connect() as conn:
        ensure_table(conn)
        rows = conn.execute(
            """
            SELECT id, user_id, goal, summary, namespace, module_titles,
                   estimated_cost_usd, with_quiz, used_style, created_at,
                   progress, opened_at,
                   jsonb_array_length(modules) AS module_count
            FROM courses
            WHERE user_id = %s
            ORDER BY COALESCE(opened_at, created_at) DESC
            LIMIT %s
            """,
            (normalize(user_id), limit),
        ).fetchall()
    return [_summary_row(r) for r in rows]


def get(course_id: int) -> dict | None:
    with db.connect() as conn:
        ensure_table(conn)
        row = conn.execute(
            """
            SELECT id, user_id, goal, summary, namespace, module_titles,
                   modules, estimated_cost_usd, with_quiz, used_style,
                   created_at, progress, opened_at
            FROM courses
            WHERE id = %s
            """,
            (course_id,),
        ).fetchone()
    if not row:
        return None
    return _full_row(row)


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


def _summary_row(row: dict) -> dict:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "goal": row["goal"],
        "summary": row["summary"],
        "namespace": row["namespace"],
        "module_titles": _parse_json(row["module_titles"]),
        "module_count": row["module_count"],
        "estimated_cost_usd": row["estimated_cost_usd"],
        "with_quiz": row["with_quiz"],
        "used_style": row["used_style"],
        "created_at": row["created_at"].isoformat()
        if hasattr(row["created_at"], "isoformat")
        else row["created_at"],
        **_progress_fields(row),
    }


def _full_row(row: dict) -> dict:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "goal": row["goal"],
        "summary": row["summary"],
        "namespace": row["namespace"],
        "module_titles": _parse_json(row["module_titles"]),
        "modules": _parse_json(row["modules"]),
        "estimated_cost_usd": row["estimated_cost_usd"],
        "with_quiz": row["with_quiz"],
        "used_style": row["used_style"],
        "created_at": row["created_at"].isoformat()
        if hasattr(row["created_at"], "isoformat")
        else row["created_at"],
        **_progress_fields(row),
    }
