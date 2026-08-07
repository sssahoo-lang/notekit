"""Choosing which sources to fetch for a topic.

Fetching every adapter for every topic wastes time and returns noise: arXiv has
nothing useful on the French Revolution, PubMed nothing on Baroque music, and
searching them anyway costs a round trip and pollutes the corpus with
low-scoring chunks the reranker then has to discard.

The router classifies the subject once per topic and picks adapters from that.
Wikipedia is always included — it is the only source that covers foundations
across every domain, and the milestone-1 finding was that arXiv alone cannot
teach basics because it indexes the research frontier rather than pedagogy.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from . import config, llm

Domain = Literal[
    "computing", "biomedical", "physical-science", "social-science",
    "humanities", "general",
]

# Which adapters actually hold material for each domain. Wikipedia is in every
# row deliberately; the others are added only where they have real coverage.
DOMAIN_SOURCES: dict[str, list[str]] = {
    "computing": ["wikipedia", "arxiv"],
    "physical-science": ["wikipedia", "arxiv"],
    "biomedical": ["wikipedia", "pubmed"],
    "social-science": ["wikipedia", "arxiv"],
    "humanities": ["wikipedia"],
    "general": ["wikipedia"],
}

_SYSTEM = """You classify a study topic into one subject domain.

- computing: computer science, software, machine learning, statistics, maths
- physical-science: physics, chemistry, astronomy, earth science, engineering
- biomedical: medicine, biology, neuroscience, genetics, public health
- social-science: economics, psychology, sociology, political science
- humanities: history, literature, philosophy, art, music, languages
- general: everyday or practical subjects fitting none of the above

Choose the single best fit. Judge the subject, not the wording of the request."""


class Routing(BaseModel):
    domain: Domain
    reason: str = Field(description="One short clause naming what decided it")


def classify(topic: str) -> Routing:
    return llm.parse(
        model=config.PLANNER_MODEL,
        system=_SYSTEM,
        prompt=f"Topic: {topic}",
        max_tokens=300,
        schema=Routing,
        purpose="route-sources",
    )


def sources_for(topic: str) -> tuple[list[str], Routing]:
    """Adapters to fetch from for this topic, and why."""
    routing = classify(topic)
    return DOMAIN_SOURCES.get(routing.domain, ["wikipedia"]), routing
