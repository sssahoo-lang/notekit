"""Asking sources for recent work.

Both adapters sorted by relevance with no alternative, so there was no way to
ask for anything published since a corpus was first built. Two design decisions are under test.

Recency is blended with relevance rather than replacing it, because a corpus of
only the newest papers is a worse corpus: the newest work assumes the standard
treatment rather than giving it.

And "recent" is expressed as relevance within a date window, not as ordering by
date. Measured against the live API, sorting arXiv by submittedDate for
"q-learning" returned semantic communication and transverse-momentum
extraction: the newest papers matching the query at all, ranked with no regard
for how weakly. The window form returned Quantile Q-Learning and Pareto
Q-Learning with Reward Machines."""

import httpx
import pytest

from notekit import config
from notekit.adapters import blend, split_budget
from notekit.adapters.arxiv import ArxivAdapter
from notekit.adapters.pubmed import PubMedAdapter
from notekit.adapters.wikipedia import WikipediaAdapter


class TestSplitBudget:
    def test_an_even_budget_halves(self):
        assert split_budget(10) == (5, 5)

    def test_relevance_gets_the_odd_one(self):
        # Relevance carries the standard treatments, so it wins the tiebreak.
        assert split_budget(7) == (4, 3)

    def test_a_budget_of_one_spends_it_on_relevance(self):
        # Never spend the only slot on a paper that assumes the basics.
        assert split_budget(1) == (1, 0)

    def test_the_whole_budget_is_always_spent(self):
        for n in range(1, 30):
            assert sum(split_budget(n)) == n


class TestBlend:
    key = staticmethod(lambda x: x)

    def test_relevance_keeps_its_order_and_comes_first(self):
        # The reranker already handles relevance-ordered candidates well.
        assert blend(["a", "b"], ["c"], key=self.key) == ["a", "b", "c"]

    def test_a_paper_found_both_ways_appears_once(self):
        assert blend(["a", "b"], ["b", "c"], key=self.key) == ["a", "b", "c"]

    def test_the_duplicate_resolves_to_the_relevance_copy(self):
        # Same id, different objects: the relevance one must survive, since it
        # is the one whose position the reranker expects.
        relevant = [{"id": "x", "from": "relevance"}]
        recent = [{"id": "x", "from": "recency"}]
        merged = blend(relevant, recent, key=lambda d: d["id"])
        assert merged == [{"id": "x", "from": "relevance"}]

    def test_either_side_may_be_empty(self):
        assert blend([], ["a"], key=self.key) == ["a"]
        assert blend(["a"], [], key=self.key) == ["a"]


class TestWhatTheSourcesAreAsked:
    """The sort parameters actually sent, captured without network access."""

    def capture(self, monkeypatch, adapter, **kwargs):
        calls: list[dict] = []

        class Response:
            status_code = 200
            text = "<feed xmlns='http://www.w3.org/2005/Atom'></feed>"

            def raise_for_status(self):
                pass

            def json(self):
                return {"esearchresult": {"idlist": []}}

        def fake_get(url, **kw):
            calls.append(kw.get("params", {}))
            return Response()

        monkeypatch.setattr(httpx, "get", fake_get)
        monkeypatch.setattr("time.sleep", lambda *_: None)
        adapter.fetch("q-learning", 10, **kwargs)
        return calls

    def test_arxiv_default_is_one_relevance_search(self, monkeypatch):
        calls = self.capture(monkeypatch, ArxivAdapter())
        assert len(calls) == 1
        assert calls[0]["sortBy"] == "relevance"
        assert calls[0]["max_results"] == 10

    def test_arxiv_recent_narrows_the_window_and_keeps_relevance_ordering(
        self, monkeypatch
    ):
        calls = self.capture(monkeypatch, ArxivAdapter(), recent=True)
        assert len(calls) == 2
        # Ordering by date is the thing this deliberately does not do.
        assert [c["sortBy"] for c in calls] == ["relevance", "relevance"]
        assert "submittedDate" not in calls[0]["search_query"]
        assert "submittedDate:[" in calls[1]["search_query"]
        # Asking for recency must not double what is fetched.
        assert sum(c["max_results"] for c in calls) == 10

    def test_arxiv_window_starts_within_the_configured_span(self, monkeypatch):
        from datetime import datetime, timedelta, timezone

        calls = self.capture(monkeypatch, ArxivAdapter(), recent=True)
        start = calls[1]["search_query"].split("submittedDate:[")[1][:12]
        parsed = datetime.strptime(start, "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
        expected = datetime.now(timezone.utc) - timedelta(
            days=config.RECENT_WINDOW_DAYS
        )
        assert abs((parsed - expected).total_seconds()) < 300

    def test_pubmed_default_is_one_relevance_search(self, monkeypatch):
        calls = self.capture(monkeypatch, PubMedAdapter())
        assert len(calls) == 1
        assert calls[0]["sort"] == "relevance"

    def test_pubmed_recent_narrows_the_window_and_keeps_relevance_ordering(
        self, monkeypatch
    ):
        calls = self.capture(monkeypatch, PubMedAdapter(), recent=True)
        assert [c["sort"] for c in calls] == ["relevance", "relevance"]
        assert "reldate" not in calls[0]
        assert calls[1]["reldate"] == config.RECENT_WINDOW_DAYS
        assert calls[1]["datetype"] == "pdat"
        assert sum(c["retmax"] for c in calls) == 10

    def test_wikipedia_accepts_recent_without_changing_its_request(self, monkeypatch):
        # Articles are revised in place, so date ordering would rank new stubs
        # above the mature pages foundational modules need.
        plain = self.capture(monkeypatch, WikipediaAdapter())
        recent = self.capture(monkeypatch, WikipediaAdapter(), recent=True)
        assert plain == recent
