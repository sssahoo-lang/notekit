"""Suggestions offered while a goal is typed."""

import contextlib

from notekit import suggest


class FakeConn:
    def __init__(self, rows): self.rows = rows
    def execute(self, sql, params=None): self.params = params; return self
    def fetchall(self): return self.rows


def test_instant_matches_own_courses_and_indexed_topics(monkeypatch):
    monkeypatch.setattr(suggest.courses, "list_for_user", lambda u: [
        {"id": 1, "title": "Machine learning basics", "goal": "teach me ml"},
        {"id": 2, "title": "Bayesian statistics", "goal": "bayes"},
    ])
    rows = [{"slug": "machine-learning", "label": "Machine learning"}]
    monkeypatch.setattr(suggest.db, "connect", lambda: contextlib.nullcontext(FakeConn(rows)))
    r = suggest.instant("machine", "u")
    assert [h["id"] for h in r["history"]] == [1]
    assert r["topics"] == [{"slug": "machine-learning", "label": "Machine learning"}]


def test_instant_needs_two_characters_and_never_calls_the_model(monkeypatch):
    monkeypatch.setattr(suggest.llm, "parse", lambda **k: (_ for _ in ()).throw(AssertionError("model called")))
    monkeypatch.setattr(suggest.courses, "list_for_user", lambda u: [])
    assert suggest.instant("m", "u") == {"history": [], "topics": []}


def test_related_is_cached_by_what_was_typed(monkeypatch):
    calls = []
    def parse(**kw):
        calls.append(kw["prompt"]); return suggest._Suggestions(goals=["a from scratch", "b for engineers", "  ", "Machine Learning"])
    monkeypatch.setattr(suggest.llm, "parse", parse)
    suggest._cache.clear()
    first = suggest.related("machine learning")
    second = suggest.related("  Machine   Learning ")
    assert first == second == ["a from scratch", "b for engineers"], "blank and verbatim echoes are dropped"
    assert len(calls) == 1, "same text, different spacing: one call"


def test_related_is_silent_below_three_characters(monkeypatch):
    monkeypatch.setattr(suggest.llm, "parse", lambda **k: (_ for _ in ()).throw(AssertionError("model called")))
    assert suggest.related("ml") == []
