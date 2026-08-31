"""PubMed adapter: biomedical literature via NCBI E-utilities.

Abstracts only, deliberately. Full text lives behind PubMed Central and varies
by licence, and an abstract is dense, self-contained and written to stand
alone, which is closer to what a study note needs than a methods section is.
"""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

# NCBI allows three requests a second without an API key. One request per second
# stays well inside that without needing one.
_POLITE_DELAY = 1.0

_HEADERS = {"User-Agent": "notekit/0.1 (https://github.com/sssahoo-lang/notekit)"}


class PubMedAdapter:
    name = "pubmed"

    def fetch(self, query: str, limit: int = 10):
        from . import SourceDocument

        pmids = self._search(query, limit)
        if not pmids:
            return []

        time.sleep(_POLITE_DELAY)
        documents = []
        for record in self._fetch_abstracts(pmids):
            # Below this an "abstract" is usually a title plus a stub, which
            # cannot support a claim.
            if len(record["abstract"]) < 300:
                continue
            documents.append(
                SourceDocument(
                    external_id=record["pmid"],
                    title=record["title"],
                    url=f"https://pubmed.ncbi.nlm.nih.gov/{record['pmid']}/",
                    text=f"{record['title']}\n\n{record['abstract']}",
                )
            )
        return documents

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=20))
    def _search(self, query: str, limit: int) -> list[str]:
        response = httpx.get(
            f"{_BASE}/esearch.fcgi",
            params={
                "db": "pubmed",
                "term": query,
                "retmax": limit,
                "retmode": "json",
                "sort": "relevance",
            },
            timeout=30,
            headers=_HEADERS,
            follow_redirects=True,
        )
        response.raise_for_status()
        return response.json().get("esearchresult", {}).get("idlist", [])

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=20))
    def _fetch_abstracts(self, pmids: list[str]) -> list[dict]:
        # efetch takes every id in one call, so this is a single round trip.
        response = httpx.get(
            f"{_BASE}/efetch.fcgi",
            params={"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"},
            timeout=60,
            headers=_HEADERS,
            follow_redirects=True,
        )
        response.raise_for_status()

        root = ET.fromstring(response.text)
        records = []
        for article in root.findall(".//PubmedArticle"):
            pmid = article.findtext(".//PMID", default="").strip()
            title = " ".join(
                (article.findtext(".//ArticleTitle", default="") or "").split()
            )
            # Structured abstracts split into labelled sections; keep the labels
            # since they carry meaning ("Methods", "Results").
            parts = []
            for node in article.findall(".//Abstract/AbstractText"):
                label = node.get("Label")
                text = " ".join("".join(node.itertext()).split())
                if not text:
                    continue
                parts.append(f"{label}: {text}" if label else text)

            if pmid and title:
                records.append(
                    {"pmid": pmid, "title": title, "abstract": "\n\n".join(parts)}
                )
        return records
