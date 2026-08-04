"""Hybrid retrieval: dense + sparse, fused, then reranked.

Reranking is both a quality and a latency lever here — tighter context means a
smaller generation prompt, so the eval story and the speed story point the same
way rather than trading off.
"""

from __future__ import annotations

from . import config, db, embedding
from .models import Chunk

# Standard reciprocal-rank-fusion constant; damps the influence of top ranks
# just enough that one list cannot dominate the other.
_RRF_K = 60


def retrieve(
    *, query: str, namespace: str, cfg: config.RetrievalConfig | None = None
) -> list[Chunk]:
    cfg = cfg or config.EMBEDDING

    with db.connect() as conn:
        dense = db.search_dense(
            conn,
            namespace=namespace,
            query_vec=embedding.embed_query(query, cfg),
            k=cfg.dense_k,
        )
        sparse = db.search_sparse(
            conn, namespace=namespace, query=query, k=cfg.sparse_k
        )

    fused = _reciprocal_rank_fusion(dense, sparse)
    if not fused:
        return []

    scores = embedding.rerank(query, [row["text"] for row in fused], cfg)
    for row, score in zip(fused, scores, strict=True):
        row["score"] = score

    ranked = sorted(fused, key=lambda r: r["score"], reverse=True)
    top = ranked[: cfg.rerank_to]

    return [
        Chunk(
            id=row["id"],
            text=row["text"],
            document_title=row["document_title"],
            document_url=row["document_url"],
            score=row["score"],
        )
        for row in top
    ]


def retrieve_multi(
    queries: list[str],
    *,
    namespace: str,
    cfg: config.RetrievalConfig | None = None,
    limit: int | None = None,
) -> list[Chunk]:
    """Retrieve for several related queries and merge the results.

    A module asks one question, but its learning goals ask several more specific
    ones. Retrieving once per goal and merging is what lets generation address
    every goal rather than only the parts the module query happened to surface.

    Each chunk keeps its best score across queries, so a passage that is highly
    relevant to one goal is not buried by being irrelevant to the others.
    """
    cfg = cfg or config.EMBEDDING
    limit = limit or config.MAX_CONTEXT_CHUNKS

    best: dict[int, Chunk] = {}
    for query in queries:
        for chunk in retrieve(query=query, namespace=namespace, cfg=cfg):
            existing = best.get(chunk.id)
            if existing is None or chunk.score > existing.score:
                best[chunk.id] = chunk

    return sorted(best.values(), key=lambda c: c.score, reverse=True)[:limit]


def _reciprocal_rank_fusion(*result_lists: list[dict]) -> list[dict]:
    """Merge ranked lists by rank position rather than by raw score.

    Dense similarity and ts_rank are on incomparable scales, so fusing on score
    would let whichever list has the larger numbers win by default.
    """
    scores: dict[int, float] = {}
    rows: dict[int, dict] = {}

    for results in result_lists:
        for rank, row in enumerate(results):
            chunk_id = row["id"]
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (_RRF_K + rank + 1)
            rows.setdefault(chunk_id, dict(row))

    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    return [rows[chunk_id] for chunk_id, _ in ordered]
