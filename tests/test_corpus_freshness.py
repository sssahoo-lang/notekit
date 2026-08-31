"""Corpus expiry and the three ways past the cache.

Before this, `ingested_at` was written and then only ever checked for being
non-null, so a topic fetched once was reused for ever. These cover the decision
about whether to fetch again. Whether the age comparison itself is right is a
question about SQL and is checked against a real database, not here."""

import contextlib
from datetime import datetime, timedelta, timezone

import pytest

from notekit import cli, config, db, ingest


class FakeDb:
    """Just enough of db.py to reach the cache decision and stop."""

    def __init__(self, *, ingested=True, populated=True, chunks=5):
        self.asked_queries: set[str] = set()
        self.ingested = ingested
        self.populated = populated
        self.chunks = chunks
        self.asked_max_age = "not asked"
        self.cleared_namespace = False
        self.cleared_cache = False

    @contextlib.contextmanager
    def connect(self):
        yield object()

    def topic_is_ingested(self, conn, slug, *, max_age_days=None):
        self.asked_max_age = max_age_days
        return self.ingested

    def topic_queries(self, conn, slug):
        # These tests are about age, not query coverage, so the corpus is
        # treated as already fetched for whatever it is asked. Coverage has
        # its own file.
        return self.asked_queries

    normalise_query = staticmethod(db.normalise_query)

    def namespace_stats(self, conn, namespace):
        return {"chunks": self.chunks, "documents": 1}

    def namespace_is_populated(self, conn, namespace):
        return self.populated

    def clear_namespace(self, conn, namespace):
        self.cleared_namespace = True

    def clear_topic_cache(self, conn, slug):
        self.cleared_cache = True

    def mark_topic_ingested(self, conn, slug, namespace, raw_goal, queries=None):
        pass


class Unreachable:
    """Stands in for a source. Reaching it means the cache was bypassed, which
    is what the fall-through tests are asserting; it fails rather than
    fetching so no test touches the network."""

    name = "unreachable"

    def fetch(self, query, limit):
        raise AssertionError("should not fetch in these tests")


def run(monkeypatch, fake, **kwargs):
    fake.asked_queries = {db.normalise_query("q-learning")}
    monkeypatch.setattr(ingest, "db", fake)
    monkeypatch.setitem(ingest.REGISTRY, "unreachable", Unreachable())
    return ingest.ingest_topic(
        slug="q-learning",
        query="q-learning",
        namespace="q-learning",
        adapter_names=["unreachable"],  # also skips the routing call
        **kwargs,
    )


def test_a_fresh_corpus_is_reused(monkeypatch):
    fake = FakeDb()
    assert run(monkeypatch, fake)["cached"] is True


def test_the_configured_age_limit_is_what_gets_asked_about(monkeypatch):
    fake = FakeDb()
    run(monkeypatch, fake)
    assert fake.asked_max_age == config.CORPUS_MAX_AGE_DAYS


def test_none_means_never_expire_and_is_not_the_default(monkeypatch):
    # None is a meaningful value here, so it has to survive being passed
    # explicitly rather than being read as "argument omitted".
    fake = FakeDb()
    run(monkeypatch, fake, max_age_days=None)
    assert fake.asked_max_age is None


def test_an_explicit_limit_overrides_the_config(monkeypatch):
    fake = FakeDb()
    run(monkeypatch, fake, max_age_days=1)
    assert fake.asked_max_age == 1


def test_refresh_does_not_consult_the_cache_at_all(monkeypatch):
    # Not "asks and ignores the answer": a refresh must not depend on the
    # topic row, which may say fresh while the reader knows better.
    fake = FakeDb()
    with pytest.raises(Exception):
        # Falls through to fetching, which the fake cannot serve.
        run(monkeypatch, fake, refresh=True)
    assert fake.asked_max_age == "not asked"
    assert fake.cleared_namespace is False, "refresh must keep existing sources"


def test_force_empties_the_namespace_but_refresh_does_not(monkeypatch):
    fake = FakeDb()
    with pytest.raises(Exception):
        run(monkeypatch, fake, force=True)
    assert fake.cleared_namespace is True
    assert fake.cleared_cache is True


class TestAgeLabel:
    def label(self, days):
        if days is None:
            return cli._corpus_age(None)
        return cli._corpus_age(datetime.now(timezone.utc) - timedelta(days=days, hours=1))

    def test_never_fetched(self):
        assert "never" in self.label(None)

    def test_today_reads_as_today(self):
        assert "today" in self.label(0)

    def test_recent_is_not_flagged(self):
        assert self.label(3) == "3d ago"

    def test_past_the_limit_is_flagged(self):
        limit = config.CORPUS_MAX_AGE_DAYS
        assert limit is not None, "test assumes expiry is on by default"
        assert self.label(limit + 1).startswith("[yellow]")
