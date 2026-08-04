"""Cold lane: fetch, parse, chunk, embed, store.

Nothing here is on the user-facing critical path. It runs once per topic and
every later course on that topic is a cache hit.
"""

from __future__ import annotations

from . import config, db, embedding
from .adapters import REGISTRY


def ingest_topic(
    *,
    slug: str,
    query: str,
    namespace: str,
    adapter_name: str = "arxiv",
    limit: int = 10,
    cfg: config.RetrievalConfig | None = None,
    force: bool = False,
) -> dict:
    """Populate a namespace for one topic. Returns a summary dict."""
    cfg = cfg or config.EMBEDDING
    adapter = REGISTRY[adapter_name]

    with db.connect() as conn:
        if not force and db.topic_is_ingested(conn, slug):
            stats = db.namespace_stats(conn, namespace)
            return {"cached": True, **stats}

    print(f"Fetching up to {limit} documents from {adapter_name} for '{query}'...")
    documents = adapter.fetch(query, limit)

    total_chunks = 0
    new_documents = 0

    with db.connect() as conn:
        for doc in documents:
            document_id = db.upsert_document(
                conn,
                namespace=namespace,
                source=adapter.name,
                external_id=doc.external_id,
                title=doc.title,
                url=doc.url,
            )
            if document_id is None:
                continue

            from .parsing import chunk as split

            texts = split(doc.text, cfg)
            if not texts:
                continue

            vectors = embedding.embed_documents(texts, cfg)
            db.insert_chunks(
                conn,
                document_id=document_id,
                namespace=namespace,
                texts=texts,
                embeddings=vectors,
            )
            new_documents += 1
            total_chunks += len(texts)
            print(f"  + {doc.title[:60]} ({len(texts)} chunks)")

        db.mark_topic_ingested(conn, slug, namespace, query)
        conn.commit()
        stats = db.namespace_stats(conn, namespace)

    return {
        "cached": False,
        "new_documents": new_documents,
        "new_chunks": total_chunks,
        **stats,
    }
