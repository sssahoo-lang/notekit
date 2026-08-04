"""Source adapters: one interface, many corpora.

Every adapter turns a topic query into `SourceDocument`s. The core engine never
knows which adapter produced a chunk, which is what lets open-domain fetching
and user uploads share the same retrieval and generation code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class SourceDocument:
    external_id: str
    title: str
    url: str | None
    text: str


class SourceAdapter(Protocol):
    name: str

    def fetch(self, query: str, limit: int) -> list[SourceDocument]: ...


from .arxiv import ArxivAdapter  # noqa: E402

REGISTRY: dict[str, SourceAdapter] = {"arxiv": ArxivAdapter()}
