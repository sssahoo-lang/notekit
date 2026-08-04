"""Postgres + pgvector access. All SQL lives here."""

from __future__ import annotations

import contextlib
from collections.abc import Iterator

import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row

from . import config


@contextlib.contextmanager
def connect() -> Iterator[psycopg.Connection]:
    with psycopg.connect(config.DATABASE_URL, row_factory=dict_row) as conn:
        register_vector(conn)
        yield conn


def topic_is_ingested(conn: psycopg.Connection, slug: str) -> bool:
    row = conn.execute(
        "SELECT ingested_at FROM topics WHERE slug = %s", (slug,)
    ).fetchone()
    return bool(row and row["ingested_at"])


def mark_topic_ingested(
    conn: psycopg.Connection, slug: str, namespace: str, raw_goal: str
) -> None:
    conn.execute(
        """
        INSERT INTO topics (slug, namespace, raw_goal, ingested_at)
        VALUES (%s, %s, %s, now())
        ON CONFLICT (slug) DO UPDATE SET ingested_at = now()
        """,
        (slug, namespace, raw_goal),
    )


def upsert_document(
    conn: psycopg.Connection,
    *,
    namespace: str,
    source: str,
    external_id: str,
    title: str,
    url: str | None,
) -> int | None:
    """Returns the new document id, or None if it was already ingested."""
    row = conn.execute(
        """
        INSERT INTO documents (namespace, source, external_id, title, url)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (namespace, source, external_id) DO NOTHING
        RETURNING id
        """,
        (namespace, source, external_id, title, url),
    ).fetchone()
    return row["id"] if row else None


def insert_chunks(
    conn: psycopg.Connection,
    *,
    document_id: int,
    namespace: str,
    texts: list[str],
    embeddings: list[list[float]],
) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO chunks (document_id, namespace, ordinal, text, embedding)
            VALUES (%s, %s, %s, %s, %s)
            """,
            [
                (document_id, namespace, i, text, emb)
                for i, (text, emb) in enumerate(zip(texts, embeddings, strict=True))
            ],
        )


def search_dense(
    conn: psycopg.Connection, *, namespace: str, query_vec: list[float], k: int
) -> list[dict]:
    if k <= 0:
        return []
    return conn.execute(
        """
        SELECT c.id, c.text, d.title AS document_title, d.url AS document_url,
               1 - (c.embedding <=> %s::vector) AS score
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE c.namespace = %s
        ORDER BY c.embedding <=> %s::vector
        LIMIT %s
        """,
        (query_vec, namespace, query_vec, k),
    ).fetchall()


def search_sparse(
    conn: psycopg.Connection, *, namespace: str, query: str, k: int
) -> list[dict]:
    if k <= 0:
        return []
    return conn.execute(
        """
        SELECT c.id, c.text, d.title AS document_title, d.url AS document_url,
               ts_rank(c.tsv, plainto_tsquery('english', %s)) AS score
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE c.namespace = %s AND c.tsv @@ plainto_tsquery('english', %s)
        ORDER BY score DESC
        LIMIT %s
        """,
        (query, namespace, query, k),
    ).fetchall()


def namespace_stats(conn: psycopg.Connection, namespace: str) -> dict:
    return conn.execute(
        """
        SELECT
            (SELECT count(*) FROM documents WHERE namespace = %s) AS documents,
            (SELECT count(*) FROM chunks WHERE namespace = %s) AS chunks
        """,
        (namespace, namespace),
    ).fetchone()
