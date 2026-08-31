"""Source adapters: one interface, many corpora.

Every adapter turns a topic query into `SourceDocument`s. The core engine never
knows which adapter produced a chunk, which is what lets open-domain fetching
and user uploads share the same retrieval and generation code.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, TypeVar

T = TypeVar("T")


@dataclass
class SourceDocument:
    external_id: str
    title: str
    url: str | None
    text: str


class SourceAdapter(Protocol):
    name: str

    def fetch(
        self, query: str, limit: int, *, recent: bool = False
    ) -> list[SourceDocument]: ...


def split_budget(limit: int) -> tuple[int, int]:
    """Divide a fetch budget between relevance and recency.

    Relevance gets the odd one, because it is the half that carries the
    standard treatments a learner needs to understand anything at all.
    """
    recent = limit // 2
    return limit - recent, recent


def blend(relevant: list[T], recent: list[T], *, key: Callable[[T], str]) -> list[T]:
    """Merge a relevance-ordered batch with a recency-ordered one.

    Sorting a source by date alone is a worse corpus, not a fresher one. The
    newest papers matching a topic are usually narrow follow-ups that assume
    the standard treatment rather than giving it, and a course built only from
    those teaches nobody. Asking for recent material should mean "the usual
    sources, plus what has appeared since", which is what this returns.

    Relevance keeps its order and comes first, so the reranker sees the
    strongest candidates in the position it already handled well. Duplicates
    resolve to the relevance copy, since the same paper found both ways is not
    two sources.
    """
    seen: set[str] = set()
    merged: list[T] = []
    for item in [*relevant, *recent]:
        k = key(item)
        if k in seen:
            continue
        seen.add(k)
        merged.append(item)
    return merged


from .arxiv import ArxivAdapter  # noqa: E402
from .pubmed import PubMedAdapter  # noqa: E402
from .wikipedia import WikipediaAdapter  # noqa: E402

REGISTRY: dict[str, SourceAdapter] = {
    "wikipedia": WikipediaAdapter(),
    "arxiv": ArxivAdapter(),
    "pubmed": PubMedAdapter(),
}

# Wikipedia first: foundational modules fail without encyclopaedic material,
# and arXiv alone refuses most of them.
DEFAULT_ADAPTERS = ["wikipedia", "arxiv"]
