"""Deciding when two ways of saying a subject mean the same corpus.

The planner emits a slug per course, and slugs drift: "reinforcement-learning",
"rl-fundamentals" and "q-learning-basics" are three names for material that
should share one index. Left alone, each becomes its own namespace, so the same
sources are fetched repeatedly, the cache never hits, and every corpus stays
thinner than it should be.

Matching is by embedding rather than string comparison, because the failure is
semantic: "RL" and "reinforcement learning" share no characters, while
"linear algebra" and "linear regression" share most of them. The embedding
model is already loaded for retrieval, so this costs nothing extra.
"""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel

from . import config, db, embedding

# Cosine similarity above which two topic names are treated as the same corpus.
# Chosen from the measurements in `notekit topics --check`: related-but-distinct
# subjects sit below this, restatements of one subject sit above it. Raising it
# fragments the corpus; lowering it merges subjects that should stay apart.
MERGE_THRESHOLD = 0.86


class TopicMatch(BaseModel):
    slug: str
    namespace: str
    similarity: float


def ensure_table(conn) -> None:
    conn.execute(
        "ALTER TABLE topics ADD COLUMN IF NOT EXISTS label TEXT"
    )
    conn.execute(
        "ALTER TABLE topics ADD COLUMN IF NOT EXISTS embedding vector(384)"
    )


def _phrase(slug: str, label: str | None = None) -> str:
    """What actually gets embedded: the readable form, not the slug."""
    return (label or slug).replace("-", " ").strip().lower()


def resolve(
    slug: str,
    *,
    label: str | None = None,
    register: bool = True,
) -> TopicMatch:
    """Return the namespace this topic should use.

    An existing topic close enough in meaning wins, so its corpus is reused.
    Otherwise the slug becomes its own namespace and is recorded for next time.
    """
    vector = embedding.embed_query(_phrase(slug, label), config.EMBEDDING)

    with db.connect() as conn:
        ensure_table(conn)

        row = conn.execute(
            "SELECT slug, namespace, embedding FROM topics WHERE slug = %s", (slug,)
        ).fetchone()
        if row:
            # Rows written before this feature existed carry no embedding, so
            # nothing could ever match them and every rephrasing started a new
            # corpus. Backfill on the way past.
            if row["embedding"] is None:
                conn.execute(
                    "UPDATE topics SET embedding = %s, label = COALESCE(label, %s) "
                    "WHERE slug = %s",
                    (vector, label, slug),
                )
                conn.commit()
            return TopicMatch(slug=row["slug"], namespace=row["namespace"], similarity=1.0)

        # pgvector's <=> is cosine distance; 1 - distance is similarity.
        best = conn.execute(
            """
            SELECT slug, namespace, 1 - (embedding <=> %s::vector) AS similarity
            FROM topics
            WHERE embedding IS NOT NULL
            ORDER BY embedding <=> %s::vector
            LIMIT 1
            """,
            (vector, vector),
        ).fetchone()

        if best and best["similarity"] >= MERGE_THRESHOLD:
            match = TopicMatch(
                slug=best["slug"],
                namespace=best["namespace"],
                similarity=float(best["similarity"]),
            )
            if register:
                # Record the alias pointing at the corpus it joined, so the
                # next identical phrasing is an exact hit rather than a search.
                conn.execute(
                    """
                    INSERT INTO topics (slug, namespace, raw_goal, label, embedding)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (slug) DO NOTHING
                    """,
                    (slug, match.namespace, label or slug, label, vector),
                )
                conn.commit()
            return match

        if register:
            conn.execute(
                """
                INSERT INTO topics (slug, namespace, raw_goal, label, embedding)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (slug) DO UPDATE
                    SET label = EXCLUDED.label, embedding = EXCLUDED.embedding
                """,
                (slug, slug, label or slug, label, vector),
            )
            conn.commit()

    return TopicMatch(slug=slug, namespace=slug, similarity=0.0)


def similarity(a: str, b: str) -> float:
    """Cosine similarity between two topic names. Used to sanity-check the
    threshold without touching the database."""
    va = np.array(embedding.embed_query(_phrase(a), config.EMBEDDING))
    vb = np.array(embedding.embed_query(_phrase(b), config.EMBEDDING))
    return float(va @ vb / (np.linalg.norm(va) * np.linalg.norm(vb)))


def backfill_embeddings() -> int:
    """Give existing topic rows an embedding so they can be matched against."""
    with db.connect() as conn:
        ensure_table(conn)
        rows = conn.execute(
            "SELECT slug, label FROM topics WHERE embedding IS NULL"
        ).fetchall()
        for r in rows:
            vector = embedding.embed_query(
                _phrase(r["slug"], r["label"]), config.EMBEDDING
            )
            conn.execute(
                "UPDATE topics SET embedding = %s WHERE slug = %s", (vector, r["slug"])
            )
        conn.commit()
    return len(rows)


def known() -> list[dict]:
    """Every topic and the corpus it resolves to."""
    with db.connect() as conn:
        ensure_table(conn)
        rows = conn.execute(
            """
            SELECT slug, namespace, label, ingested_at,
                   (SELECT count(*) FROM chunks c WHERE c.namespace = t.namespace) AS chunks
            FROM topics t
            ORDER BY namespace, slug
            """
        ).fetchall()
    return [dict(r) for r in rows]
