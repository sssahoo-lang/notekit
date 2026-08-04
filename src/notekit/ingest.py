"""Cold lane: fetch, parse, chunk, embed, store.

Nothing here is on the user-facing critical path. It runs once per topic and
every later course on that topic is a cache hit.
"""

from __future__ import annotations

from . import config, db, embedding
from .adapters import DEFAULT_ADAPTERS, REGISTRY


def ingest_topic(
    *,
    slug: str,
    query: str,
    namespace: str,
    adapter_names: list[str] | None = None,
    limit: int = 10,
    cfg: config.RetrievalConfig | None = None,
    force: bool = False,
) -> dict:
    """Populate a namespace for one topic. Returns a summary dict."""
    cfg = cfg or config.EMBEDDING
    adapter_names = adapter_names or DEFAULT_ADAPTERS

    with db.connect() as conn:
        if not force and db.topic_is_ingested(conn, slug):
            stats = db.namespace_stats(conn, namespace)
            return {"cached": True, **stats}

    fetched: list[tuple[str, object]] = []
    for name in adapter_names:
        adapter = REGISTRY[name]
        print(f"Fetching up to {limit} documents from {name} for '{query}'...")
        try:
            for doc in adapter.fetch(query, limit):
                fetched.append((adapter.name, doc))
        except Exception as exc:  # noqa: BLE001
            # One unreachable source should not lose the material from the
            # others — a partial corpus still produces grounded notes.
            print(f"  ! {name} failed: {exc}")

    total_chunks = 0
    new_documents = 0

    with db.connect() as conn:
        for source_name, doc in fetched:
            document_id = db.upsert_document(
                conn,
                namespace=namespace,
                source=source_name,
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
            print(f"  + [{source_name}] {doc.title[:52]} ({len(texts)} chunks)")

        db.mark_topic_ingested(conn, slug, namespace, query)
        conn.commit()
        stats = db.namespace_stats(conn, namespace)

    return {
        "cached": False,
        "new_documents": new_documents,
        "new_chunks": total_chunks,
        **stats,
    }
