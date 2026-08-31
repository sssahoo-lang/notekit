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


def topic_is_ingested(
    conn: psycopg.Connection, slug: str, *, max_age_days: int | None = None
) -> bool:
    """Whether this topic has a corpus that is still considered current.

    The age comparison runs in SQL rather than against the local clock, so it
    uses the same source of truth as `mark_topic_ingested`'s `now()`. A client
    in a different timezone, or one whose clock has drifted, cannot decide that
    a corpus written seconds ago is already stale.

    `max_age_days=None` means never expire, which is what this did before ages
    were considered at all.
    """
    row = conn.execute(
        """
        SELECT ingested_at IS NOT NULL AS ingested,
               (%s::int IS NULL
                OR ingested_at > now() - make_interval(days => %s::int)) AS fresh
        FROM topics WHERE slug = %s
        """,
        (max_age_days, max_age_days, slug),
    ).fetchone()
    return bool(row and row["ingested"] and row["fresh"])


def clear_topic_cache(conn: psycopg.Connection, slug: str) -> None:
    """Forget that a topic was ingested so the next run fetches again."""
    conn.execute(
        "UPDATE topics SET ingested_at = NULL WHERE slug = %s",
        (slug,),
    )


def mark_topic_ingested(
    conn: psycopg.Connection, slug: str, namespace: str, raw_goal: str
) -> None:
    conn.execute(
        """
        INSERT INTO topics (slug, namespace, raw_goal, ingested_at)
        VALUES (%s, %s, %s, now())
        ON CONFLICT (slug) DO UPDATE SET
            ingested_at = now(),
            namespace = EXCLUDED.namespace,
            raw_goal = EXCLUDED.raw_goal
        """,
        (slug, namespace, raw_goal),
    )


def namespace_stats(conn: psycopg.Connection, namespace: str) -> dict:
    return conn.execute(
        """
        SELECT
            (SELECT count(*) FROM documents WHERE namespace = %s) AS documents,
            (SELECT count(*) FROM chunks WHERE namespace = %s) AS chunks
        """,
        (namespace, namespace),
    ).fetchone()


def namespace_is_populated(conn: psycopg.Connection, namespace: str) -> bool:
    """True when the namespace has at least one searchable chunk."""
    row = namespace_stats(conn, namespace)
    return int(row["chunks"] or 0) > 0


def clear_namespace(conn: psycopg.Connection, namespace: str) -> None:
    """Delete every document (and cascaded chunk) in a namespace."""
    conn.execute("DELETE FROM documents WHERE namespace = %s", (namespace,))


def upsert_document(
    conn: psycopg.Connection,
    *,
    namespace: str,
    source: str,
    external_id: str,
    title: str,
    url: str | None,
) -> int | None:
    """Insert a new document. Returns its id, or None if it already exists."""
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


def get_document_id(
    conn: psycopg.Connection,
    *,
    namespace: str,
    source: str,
    external_id: str,
) -> int | None:
    row = conn.execute(
        """
        SELECT id FROM documents
        WHERE namespace = %s AND source = %s AND external_id = %s
        """,
        (namespace, source, external_id),
    ).fetchone()
    return int(row["id"]) if row else None


def upsert_or_replace_document(
    conn: psycopg.Connection,
    *,
    namespace: str,
    source: str,
    external_id: str,
    title: str,
    url: str | None,
) -> tuple[int, bool]:
    """Insert or refresh document metadata.

    Returns `(document_id, created)`. When `created` is False the caller should
    replace chunks if the content may have changed; when True, insert chunks.
    """
    row = conn.execute(
        """
        INSERT INTO documents (namespace, source, external_id, title, url)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (namespace, source, external_id) DO UPDATE SET
            title = EXCLUDED.title,
            url = EXCLUDED.url
        RETURNING id, (xmax = 0) AS created
        """,
        (namespace, source, external_id, title, url),
    ).fetchone()
    return int(row["id"]), bool(row["created"])


def delete_chunks_for_document(conn: psycopg.Connection, document_id: int) -> None:
    conn.execute("DELETE FROM chunks WHERE document_id = %s", (document_id,))


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


def replace_chunks(
    conn: psycopg.Connection,
    *,
    document_id: int,
    namespace: str,
    texts: list[str],
    embeddings: list[list[float]],
) -> None:
    """Swap a document's chunks for a fresh set (used when content changes)."""
    delete_chunks_for_document(conn, document_id)
    insert_chunks(
        conn,
        document_id=document_id,
        namespace=namespace,
        texts=texts,
        embeddings=embeddings,
    )


def get_chunks_by_ids(conn: psycopg.Connection, chunk_ids: list[int]) -> list[dict]:
    """Load chunk rows (with document titles) in the order of `chunk_ids`."""
    if not chunk_ids:
        return []
    rows = conn.execute(
        """
        SELECT c.id, c.text, d.title AS document_title, d.url AS document_url,
               0.0 AS score
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE c.id = ANY(%s)
        """,
        (chunk_ids,),
    ).fetchall()
    by_id = {int(r["id"]): dict(r) for r in rows}
    return [by_id[i] for i in chunk_ids if i in by_id]


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
        WHERE c.namespace = %s AND c.embedding IS NOT NULL
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
