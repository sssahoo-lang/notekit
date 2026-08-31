"""Whether a cached corpus can answer the syllabus in front of it.

A second course on a subject gets a different syllabus. One built for system
design planned four modules; the next planned five, the extra one on monitoring
and observability. The corpus was cached, so its query never ran, and the
section refused: the passages covered hardware fault models, not tracing or
SLOs. Correct, and useless.

A topic being "ingested" says nothing about which questions its corpus can
answer, so the queries it was fetched for are recorded and compared."""

import contextlib

import pytest

from notekit import db, ingest


class FakeConn:
    """The connection surface ingest touches once it decides to write."""

    def commit(self):
        pass


class FakeDb:
    """db.py's surface, down to the decision about what to fetch."""

    def __init__(self, *, done=(), chunks=5):
        self.done = {db.normalise_query(q) for q in done}
        self.chunks = chunks
        self.marked_with: list[str] | None = None
        self.fetched: list[str] = []

    @contextlib.contextmanager
    def connect(self):
        yield FakeConn()

    def topic_is_ingested(self, conn, slug, *, max_age_days=None):
        return True

    def topic_queries(self, conn, slug):
        return self.done

    normalise_query = staticmethod(db.normalise_query)

    def namespace_stats(self, conn, namespace):
        return {"chunks": self.chunks, "documents": 3}

    def namespace_is_populated(self, conn, namespace):
        return self.chunks > 0

    def clear_namespace(self, conn, namespace):
        pass

    def clear_topic_cache(self, conn, slug):
        pass

    def mark_topic_ingested(self, conn, slug, namespace, raw_goal, queries=None):
        self.marked_with = list(queries or [])

    def upsert_document(self, conn, **kw):
        return None


class Recorder:
    name = "recorder"

    def __init__(self, sink):
        self.sink = sink

    def fetch(self, query, limit, *, recent=False):
        self.sink.append(query)
        return []


def run(monkeypatch, fake, queries):
    monkeypatch.setattr(ingest, "db", fake)
    monkeypatch.setitem(ingest.REGISTRY, "recorder", Recorder(fake.fetched))
    return ingest.ingest_topic(
        slug="system-design",
        query=queries,
        namespace="system-design",
        adapter_names=["recorder"],
    )


ALL = ["distributed systems", "consistency models", "monitoring observability"]


def test_a_corpus_built_for_every_query_is_a_cache_hit(monkeypatch):
    fake = FakeDb(done=ALL)
    assert run(monkeypatch, fake, ALL)["cached"] is True
    assert fake.fetched == [], "nothing should be refetched"


def test_a_query_never_fetched_is_fetched_now(monkeypatch):
    # The monitoring module that refused.
    fake = FakeDb(done=ALL[:2])
    result = run(monkeypatch, fake, ALL)
    assert result["cached"] is False
    assert fake.fetched == ["monitoring observability"]


def test_the_queries_already_covered_are_not_fetched_again(monkeypatch):
    # Topping up must stay cheap, or every new module refetches the subject.
    fake = FakeDb(done=ALL[:1])
    run(monkeypatch, fake, ALL)
    assert "distributed systems" not in fake.fetched
    assert len(fake.fetched) == 2


def test_spacing_and_case_do_not_count_as_a_new_query(monkeypatch):
    fake = FakeDb(done=["Distributed  Systems"])
    assert run(monkeypatch, fake, ["distributed systems"])["cached"] is True


def test_a_topic_with_no_recorded_queries_is_treated_as_covering_none(monkeypatch):
    # Corpora built before queries were recorded. Assuming they cover a new
    # syllabus is the bug; the top-up is additive and costs no API spend.
    fake = FakeDb(done=[])
    run(monkeypatch, fake, ALL)
    assert fake.fetched == ALL


def test_an_empty_namespace_refetches_everything(monkeypatch):
    # A topic row can outlive its chunks.
    fake = FakeDb(done=ALL, chunks=0)
    run(monkeypatch, fake, ALL)
    assert fake.fetched == ALL


def test_what_gets_recorded_is_what_was_fetched(monkeypatch):
    fake = FakeDb(done=ALL[:2])
    run(monkeypatch, fake, ALL)
    assert fake.marked_with == ["monitoring observability"]


@pytest.mark.parametrize(
    "raw,expected",
    [("  A  B ", "a b"), ("A\tB", "a b"), ("a b", "a b")],
)
def test_normalise_query(raw, expected):
    assert db.normalise_query(raw) == expected
