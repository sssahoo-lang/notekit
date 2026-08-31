"""Wikipedia adapter: encyclopaedic material for foundational modules.

arXiv indexes the research frontier, which makes it a poor source for "explain
the basics of X". See the milestone 1 finding in the README. Wikipedia covers
exactly that gap, and needs no PDF parsing since the API returns plain text.
"""

from __future__ import annotations

import re

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

_API = "https://en.wikipedia.org/w/api.php"

# Wikimedia's robot policy returns 403 unless the User-Agent carries a contact
# URL or address: https://w.wiki/4wJS
_HEADERS = {"User-Agent": "notekit/0.1 (https://github.com/sssahoo-lang/notekit)"}

# Trailing sections carry no teachable content but match well against almost any
# query, so they crowd out real material in retrieval.
_TRAILING_SECTIONS = re.compile(
    r"\n==+ *(see also|references|external links|further reading|notes|"
    r"bibliography|sources|citations) *=+",
    re.IGNORECASE,
)
_HEADINGS = re.compile(r"\n=+ *([^=\n]+?) *=+\n")


class WikipediaAdapter:
    name = "wikipedia"

    def fetch(self, query: str, limit: int = 10):
        from . import SourceDocument

        hits = self._search(query, limit)
        if not hits:
            return []

        extracts = self._extracts([h["pageid"] for h in hits])
        documents = []

        for hit in hits:
            text = clean(extracts.get(hit["pageid"], ""))
            # Stubs and disambiguation pages are too thin to ground notes on.
            if len(text) < 800:
                continue
            documents.append(
                SourceDocument(
                    external_id=str(hit["pageid"]),
                    title=hit["title"],
                    url=f"https://en.wikipedia.org/?curid={hit['pageid']}",
                    text=text,
                )
            )
        return documents

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=20))
    def _search(self, query: str, limit: int) -> list[dict]:
        response = httpx.get(
            _API,
            params={
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srlimit": limit,
                "srnamespace": 0,
                "format": "json",
            },
            timeout=30,
            headers=_HEADERS,
            follow_redirects=True,
        )
        response.raise_for_status()
        return response.json().get("query", {}).get("search", [])

    def _extracts(self, page_ids: list[int]) -> dict[int, str]:
        """Fetch full plain-text extracts, one page per request.

        `exlimit` only batches when `exintro` is set. Asking for full extracts
        with several pageids silently returns just the first, so batching here
        drops every article but one.
        """
        results: dict[int, str] = {}
        for page_id in page_ids:
            try:
                results[page_id] = self._extract_one(page_id)
            except Exception as exc:  # noqa: BLE001
                print(f"  ! wikipedia page {page_id}: {exc}")
        return results

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=20))
    def _extract_one(self, page_id: int) -> str:
        response = httpx.get(
            _API,
            params={
                "action": "query",
                "prop": "extracts",
                "explaintext": 1,
                "pageids": page_id,
                "format": "json",
            },
            timeout=60,
            headers=_HEADERS,
            follow_redirects=True,
        )
        response.raise_for_status()
        pages = response.json().get("query", {}).get("pages", {})
        return pages.get(str(page_id), {}).get("extract", "")


def clean(text: str) -> str:
    match = _TRAILING_SECTIONS.search(text)
    if match:
        text = text[: match.start()]
    # Keep heading words as plain text: they carry topic signal for BM25, but
    # the "==" markup is noise inside a retrieved passage.
    text = _HEADINGS.sub(r"\n\n\1\n\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()
