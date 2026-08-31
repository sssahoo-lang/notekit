"""Cold lane: fetch, parse, chunk, embed, store.

Nothing here is on the user-facing critical path. It runs once per topic and
every later course on that topic is a cache hit, but only when the namespace
actually has searchable chunks.
"""

from __future__ import annotations

from . import config, db, embedding
from . import router
from .adapters import DEFAULT_ADAPTERS, REGISTRY


# None is a meaningful value for max_age_days ("never expire"), so the
# default cannot be None. This distinguishes "not passed" from "passed None".
_UNSET: int | None = -1


def ingest_topic(
    *,
    slug: str,
    query: str | list[str],
    namespace: str,
    adapter_names: list[str] | None = None,
    limit: int = 10,
    cfg: config.RetrievalConfig | None = None,
    force: bool = False,
    refresh: bool = False,
    recent: bool = False,
    max_age_days: int | None = _UNSET,
) -> dict:
    """Populate a namespace for one topic. Returns a summary dict.

    `query` may be a list. Fetching per module query rather than on the topic
    alone is what gives each module material to work from: a corpus assembled
    from "q-learning" answers the topic broadly but leaves specific modules
    thin, which shows up later as low coverage.

    Three ways past the cache, and the difference matters:

    `force` rebuilds. The namespace is emptied first, so anything the sources
    have dropped since disappears here too, and everything is embedded again.

    `refresh` tops up. Documents are keyed on (namespace, source, external_id)
    and inserted with ON CONFLICT DO NOTHING, so what is already indexed is
    kept and skipped, and only genuinely new material is fetched and embedded.
    This is what a reader wants when they ask for newer sources: papers
    published since last time, without paying to re-embed the corpus.

    `max_age_days` is the same top-up, applied automatically once the corpus
    passes an age. It defaults to `config.CORPUS_MAX_AGE_DAYS`; pass None to
    disable expiry for one call.

    `recent` asks each source for newly published work alongside the most
    relevant, rather than instead of it. See `adapters.blend` for why the
    distinction matters.
    """
    cfg = cfg or config.EMBEDDING
    max_age = config.CORPUS_MAX_AGE_DAYS if max_age_days is _UNSET else max_age_days
    if adapter_names is None:
        # No explicit choice: pick sources by subject rather than always
        # fetching the same two. arXiv has nothing on the French Revolution.
        try:
            adapter_names, routing = router.sources_for(slug.replace("-", " "))
            print(f"Sources for '{slug}': {routing.domain} -> {', '.join(adapter_names)}")
        except Exception as exc:  # noqa: BLE001
            # Routing is an optimisation; failing it must not stop ingestion.
            print(f"  ! routing failed ({exc}); using defaults")
            adapter_names = DEFAULT_ADAPTERS
    queries = [query] if isinstance(query, str) else list(dict.fromkeys(query))
    raw_goal = query if isinstance(query, str) else " | ".join(queries)

    with db.connect() as conn:
        # Recorded before anything is fetched, so the summary can say whether
        # this topped up an existing corpus or built one from nothing.
        had_corpus = db.namespace_is_populated(conn, namespace) and not force
        if force:
            # Force means "rebuild this corpus", not "skip the topic row check
            # while leaving stale documents in place".
            db.clear_namespace(conn, namespace)
            db.clear_topic_cache(conn, slug)
            conn.commit()
        elif not refresh and db.topic_is_ingested(
            conn, slug, max_age_days=max_age
        ):
            stats = db.namespace_stats(conn, namespace)
            # A cached topic is only usable for the questions it was built to
            # answer. The second course on a subject gets a different syllabus,
            # and a module whose query never ran is asking of a corpus that was
            # never fetched for it: it refuses, correctly and uselessly. Those
            # queries are fetched now, and only those, so a cache hit stays a
            # cache hit for everything already covered.
            done = db.topic_queries(conn, slug)
            unfetched = [q for q in queries if db.normalise_query(q) not in done]
            if int(stats["chunks"] or 0) > 0 and not unfetched:
                return {"cached": True, **stats}
            if int(stats["chunks"] or 0) > 0:
                queries = unfetched
                print(
                    f"Corpus exists but was never fetched for "
                    f"{len(unfetched)} of its queries; topping up."
                )
            # Cache row exists but the namespace is empty, so treat it as a miss.
            db.clear_topic_cache(conn, slug)
            conn.commit()

    # `limit` is the budget for the whole topic, split across queries, so adding
    # modules does not multiply fetch time (arXiv wants 3s between requests).
    per_query = max(2, limit // len(queries))

    fetched: list[tuple[str, object]] = []
    for name in adapter_names:
        adapter = REGISTRY[name]
        print(f"Fetching from {name}: {len(queries)} queries x {per_query} docs...")
        for q in queries:
            try:
                for doc in adapter.fetch(q, per_query, recent=recent):
                    fetched.append((adapter.name, doc))
            except Exception as exc:  # noqa: BLE001
                # One unreachable source should not lose the material from the
                # others. A partial corpus still produces grounded notes.
                print(f"  ! {name} failed on '{q[:40]}': {exc}")

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

        stats = db.namespace_stats(conn, namespace)
        # Never cache an empty corpus, which would permanently block re-ingest.
        if int(stats["chunks"] or 0) > 0:
            db.mark_topic_ingested(conn, slug, namespace, raw_goal, queries)
        else:
            db.clear_topic_cache(conn, slug)
        conn.commit()

    return {
        "cached": False,
        "refreshed": had_corpus,
        "new_documents": new_documents,
        "new_chunks": total_chunks,
        **stats,
    }
