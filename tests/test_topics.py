"""Topic identity resolves by embedding, not string matching -- "RL" and
"reinforcement learning" share no characters but should share a corpus. The
database and the embedding model are faked here: real Postgres/pgvector and a
loaded sentence-transformer are what make this slow and API-key-free unit
testing impractical, but the branching logic (exact match, threshold merge,
new topic, backfill) is exactly what's worth pinning down independent of
either."""

import contextlib

import pytest

from notekit import topics


class FakeCursor:
    def __init__(self, row=None, rows=None):
        self._row = row
        self._rows = rows or []

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows


class FakeConn:
    """Dispatches on distinctive SQL substrings, like the real queries in
    topics.py. Records everything executed so tests can assert on it."""

    def __init__(self, exact_row=None, best_row=None, null_embedding_rows=None):
        self.exact_row = exact_row
        self.best_row = best_row
        self.null_embedding_rows = null_embedding_rows or []
        self.executed: list[tuple[str, tuple]] = []
        self.committed = False

    def execute(self, sql, params=()):
        self.executed.append((" ".join(sql.split()), params))
        s = sql.lower()
        if "alter table" in s:
            return FakeCursor()
        if "select slug, namespace, embedding from topics where slug" in s:
            return FakeCursor(row=self.exact_row)
        if "order by embedding <=>" in s:
            return FakeCursor(row=self.best_row)
        if "select slug, label from topics where embedding is null" in s:
            return FakeCursor(rows=self.null_embedding_rows)
        return FakeCursor()

    def commit(self):
        self.committed = True

    def calls_matching(self, needle: str):
        return [c for c in self.executed if needle.lower() in c[0].lower()]


@pytest.fixture
def fake_db(monkeypatch):
    """Patches topics.db.connect and topics.embedding.embed_query. Returns a
    function that installs a given FakeConn as the one `with db.connect()`
    will yield."""
    state = {"conn": None}

    @contextlib.contextmanager
    def fake_connect():
        yield state["conn"]

    monkeypatch.setattr(topics.db, "connect", fake_connect)
    monkeypatch.setattr(
        topics.embedding, "embed_query", lambda text, cfg: [0.1, 0.2, 0.3]
    )

    def install(conn: FakeConn) -> FakeConn:
        state["conn"] = conn
        return conn

    return install


def test_phrase_strips_hyphens_and_case():
    assert topics._phrase("reinforcement-learning") == "reinforcement learning"
    assert topics._phrase("RL", label="Reinforcement Learning") == "reinforcement learning"


def test_similarity_is_one_for_identical_vectors(monkeypatch):
    monkeypatch.setattr(
        topics.embedding, "embed_query", lambda text, cfg: [1.0, 2.0, 3.0]
    )
    assert topics.similarity("a", "b") == pytest.approx(1.0)


def test_similarity_is_zero_for_orthogonal_vectors(monkeypatch):
    vectors = {"x": [1.0, 0.0], "y": [0.0, 1.0]}
    monkeypatch.setattr(
        topics.embedding, "embed_query", lambda text, cfg: vectors[text]
    )
    assert topics.similarity("x", "y") == pytest.approx(0.0, abs=1e-9)


def test_exact_slug_match_returns_similarity_one_and_does_not_write(fake_db):
    conn = fake_db(FakeConn(exact_row={
        "slug": "reinforcement-learning", "namespace": "reinforcement-learning",
        "embedding": [0.1, 0.2, 0.3],
    }))
    match = topics.resolve("reinforcement-learning")
    assert match.namespace == "reinforcement-learning"
    assert match.similarity == 1.0
    assert not conn.calls_matching("UPDATE topics")
    assert not conn.calls_matching("INSERT INTO topics")


def test_exact_match_with_null_embedding_gets_backfilled(fake_db):
    conn = fake_db(FakeConn(exact_row={
        "slug": "rl", "namespace": "rl", "embedding": None,
    }))
    match = topics.resolve("rl", label="Reinforcement Learning")
    assert match.namespace == "rl"
    updates = conn.calls_matching("UPDATE topics SET embedding")
    assert len(updates) == 1
    assert conn.committed is True


def test_new_slug_above_threshold_merges_into_existing_namespace(fake_db):
    conn = fake_db(FakeConn(best_row={
        "slug": "reinforcement-learning", "namespace": "reinforcement-learning",
        "similarity": 0.91,
    }))
    match = topics.resolve("rl-fundamentals")
    assert match.namespace == "reinforcement-learning"
    assert match.similarity == pytest.approx(0.91)
    # Registers the new slug as an alias pointing at the corpus it joined.
    inserts = conn.calls_matching("INSERT INTO topics")
    assert len(inserts) == 1
    assert inserts[0][1][0] == "rl-fundamentals"
    assert inserts[0][1][1] == "reinforcement-learning"


def test_new_slug_below_threshold_becomes_its_own_namespace(fake_db):
    conn = fake_db(FakeConn(best_row={
        "slug": "linear-algebra", "namespace": "linear-algebra",
        "similarity": 0.42,
    }))
    match = topics.resolve("sourdough-fermentation")
    assert match.namespace == "sourdough-fermentation"
    assert match.similarity == 0.0
    inserts = conn.calls_matching("INSERT INTO topics")
    assert len(inserts) == 1
    assert inserts[0][1][1] == "sourdough-fermentation"


def test_no_existing_topics_at_all_becomes_its_own_namespace(fake_db):
    conn = fake_db(FakeConn(best_row=None))
    match = topics.resolve("brand-new-subject")
    assert match.namespace == "brand-new-subject"
    assert match.similarity == 0.0


def test_register_false_never_writes_even_on_a_merge(fake_db):
    conn = fake_db(FakeConn(best_row={
        "slug": "reinforcement-learning", "namespace": "reinforcement-learning",
        "similarity": 0.95,
    }))
    match = topics.resolve("rl-fundamentals", register=False)
    assert match.namespace == "reinforcement-learning"
    assert not conn.calls_matching("INSERT INTO topics")
    assert conn.committed is False


def test_register_false_on_a_new_topic_still_returns_it_unsaved(fake_db):
    conn = fake_db(FakeConn(best_row=None))
    match = topics.resolve("ephemeral-check", register=False)
    assert match.namespace == "ephemeral-check"
    assert not conn.calls_matching("INSERT INTO topics")


def test_similarity_exactly_at_threshold_counts_as_a_merge(fake_db):
    conn = fake_db(FakeConn(best_row={
        "slug": "x", "namespace": "x", "similarity": topics.MERGE_THRESHOLD,
    }))
    match = topics.resolve("y")
    assert match.namespace == "x"


def test_backfill_embeddings_only_touches_null_rows(fake_db):
    conn = fake_db(FakeConn(null_embedding_rows=[
        {"slug": "a", "label": None}, {"slug": "b", "label": "B Label"},
    ]))
    count = topics.backfill_embeddings()
    assert count == 2
    updates = conn.calls_matching("UPDATE topics SET embedding")
    assert len(updates) == 2
    assert conn.committed is True


def test_backfill_embeddings_is_a_no_op_when_nothing_is_missing(fake_db):
    conn = fake_db(FakeConn(null_embedding_rows=[]))
    assert topics.backfill_embeddings() == 0
