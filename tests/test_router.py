"""The router decides which source adapters get fetched for a topic. The
data table (DOMAIN_SOURCES) is the part with real consequences -- get a
domain's sources wrong and every course in that domain either wastes a round
trip on an adapter with nothing to say, or misses a source that does. classify()
itself is one Haiku call, mocked here so the routing logic is tested without
hitting the API."""

import pytest

from notekit import router
from notekit.router import DOMAIN_SOURCES, Routing, sources_for


def test_wikipedia_is_in_every_domain():
    # Wikipedia is the only source that covers foundations across every
    # subject; dropping it from a row silently breaks the "explain the
    # basics" case for that domain.
    for domain, sources in DOMAIN_SOURCES.items():
        assert "wikipedia" in sources, f"{domain} is missing wikipedia"


def test_arxiv_is_scoped_to_domains_with_real_coverage():
    # arXiv indexes the research frontier, not pedagogy -- it belongs only
    # where the milestone-1 finding said it actually helps.
    assert "arxiv" in DOMAIN_SOURCES["computing"]
    assert "arxiv" in DOMAIN_SOURCES["physical-science"]
    assert "arxiv" not in DOMAIN_SOURCES["humanities"]
    assert "arxiv" not in DOMAIN_SOURCES["biomedical"]


def test_pubmed_is_scoped_to_biomedical_only():
    assert "pubmed" in DOMAIN_SOURCES["biomedical"]
    for domain, sources in DOMAIN_SOURCES.items():
        if domain != "biomedical":
            assert "pubmed" not in sources, f"pubmed leaked into {domain}"


def test_every_declared_domain_has_a_source_list():
    for domain in [
        "computing", "biomedical", "physical-science", "social-science",
        "humanities", "general",
    ]:
        assert domain in DOMAIN_SOURCES
        assert len(DOMAIN_SOURCES[domain]) > 0


def test_sources_for_uses_the_classifier_domain(monkeypatch):
    monkeypatch.setattr(
        router, "classify",
        lambda topic: Routing(domain="biomedical", reason="mentions genetics"),
    )
    sources, routing = sources_for("CRISPR gene editing")
    assert sources == ["wikipedia", "pubmed"]
    assert routing.domain == "biomedical"


def test_sources_for_falls_back_to_wikipedia_for_an_unmapped_domain(monkeypatch):
    # classify() is constrained to the Domain Literal, so this can only
    # happen if the schema and the table ever drift apart -- worth covering
    # so that drift fails safe rather than raising a KeyError.
    monkeypatch.setattr(
        router, "classify",
        lambda topic: Routing.model_construct(domain="nonexistent", reason="x"),
    )
    sources, _ = sources_for("something odd")
    assert sources == ["wikipedia"]


@pytest.mark.parametrize(
    "domain,expected",
    [
        ("computing", ["wikipedia", "arxiv"]),
        ("humanities", ["wikipedia"]),
        ("general", ["wikipedia"]),
    ],
)
def test_sources_for_matches_the_domain_table(monkeypatch, domain, expected):
    monkeypatch.setattr(
        router, "classify", lambda topic: Routing(domain=domain, reason="x"),
    )
    sources, _ = sources_for("some topic")
    assert sources == expected
