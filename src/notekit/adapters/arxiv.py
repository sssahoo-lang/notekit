"""arXiv adapter: search the API, download PDFs, extract full text."""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from .. import config
from ..parsing import PyMuPDFParser

# Must be https: the http endpoint 301s, and an unfollowed redirect raises.
_API = "https://export.arxiv.org/api/query"
_NS = {"atom": "http://www.w3.org/2005/Atom"}

# arXiv asks for no more than one request every three seconds.
_POLITE_DELAY = 3.0

_HEADERS = {"User-Agent": "notekit/0.1 (study-notes research prototype)"}

# arXiv date ranges need both ends. Papers are not submitted in the future,
# so an open upper bound is written as one far enough out to never bind.
_FUTURE = "999912312359"


class ArxivAdapter:
    name = "arxiv"

    def __init__(self) -> None:
        self._parser = PyMuPDFParser()

    def fetch(self, query: str, limit: int = 10, *, recent: bool = False):
        from . import SourceDocument, blend, split_budget

        if recent:
            n_relevant, n_recent = split_budget(limit)
            by_relevance = self._search(query, n_relevant)
            # arXiv asks for a gap between requests, and asking for recency
            # means two searches where there was one.
            time.sleep(_POLITE_DELAY)
            entries = blend(
                by_relevance,
                self._search(query, n_recent, within_days=config.RECENT_WINDOW_DAYS),
                key=lambda e: e["external_id"],
            )
        else:
            entries = self._search(query, limit)
        documents = []

        for entry in entries:
            try:
                pdf_bytes = self._download(entry["pdf_url"])
                text = self._parser.extract(pdf_bytes)
            except Exception as exc:  # noqa: BLE001
                # A single unparseable PDF should not abort ingestion. Fall back
                # to the abstract, which is always clean.
                print(f"  ! {entry['external_id']}: {exc}; using abstract only")
                text = entry["abstract"]

            if len(text) < 500:
                text = entry["abstract"]

            documents.append(
                SourceDocument(
                    external_id=entry["external_id"],
                    title=entry["title"],
                    url=entry["abs_url"],
                    text=text,
                )
            )
            time.sleep(_POLITE_DELAY)

        return documents

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=20))
    def _search(
        self, query: str, limit: int, *, within_days: int | None = None
    ) -> list[dict]:
        """Search arXiv, optionally restricted to recently submitted work.

        The ordering stays relevance either way. `within_days` narrows what is
        eligible rather than changing how what is eligible gets ranked, which
        is the difference between recent work on the topic and whatever was
        posted most recently.
        """
        search_query = f"all:{query}"
        if within_days is not None:
            start = datetime.now(timezone.utc) - timedelta(days=within_days)
            search_query += (
                f" AND submittedDate:[{start:%Y%m%d%H%M} TO {_FUTURE}]"
            )
        response = httpx.get(
            _API,
            params={
                "search_query": search_query,
                "start": 0,
                "max_results": limit,
                "sortBy": "relevance",
            },
            timeout=30,
            follow_redirects=True,
            headers=_HEADERS,
        )
        response.raise_for_status()

        root = ET.fromstring(response.text)
        results = []
        for entry in root.findall("atom:entry", _NS):
            abs_url = entry.findtext("atom:id", default="", namespaces=_NS)
            external_id = abs_url.rsplit("/", 1)[-1]
            results.append(
                {
                    "external_id": external_id,
                    "title": " ".join(
                        entry.findtext("atom:title", "", _NS).split()
                    ),
                    "abstract": " ".join(
                        entry.findtext("atom:summary", "", _NS).split()
                    ),
                    "abs_url": abs_url,
                    "pdf_url": abs_url.replace("/abs/", "/pdf/"),
                }
            )
        return results

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=20))
    def _download(self, pdf_url: str) -> bytes:
        response = httpx.get(
            pdf_url, timeout=60, follow_redirects=True, headers=_HEADERS
        )
        response.raise_for_status()
        return response.content
