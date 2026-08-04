"""PDF text extraction and chunking.

Research-paper PDFs are the messiest input in the project: two-column layout,
inline math, running headers, and a reference section that is pure retrieval
noise. `PyMuPDFParser` is a first pass, deliberately behind a Protocol so it can
be swapped for a LaTeX-source or layout-aware parser without touching ingestion.
"""

from __future__ import annotations

import re
from typing import Protocol

from . import config

# Everything from a references heading to the end of the document is dropped:
# citations match well against almost any query and crowd out real content.
_REFERENCES = re.compile(
    r"\n\s*(references|bibliography)\s*\n", re.IGNORECASE
)
_ARXIV_STAMP = re.compile(r"arXiv:\d{4}\.\d{4,5}v\d+\s+\[[^\]]+\]\s+\d+\s+\w+\s+\d{4}")
_WHITESPACE = re.compile(r"[ \t]+")
_BLANK_LINES = re.compile(r"\n{3,}")


class PDFParser(Protocol):
    def extract(self, pdf_bytes: bytes) -> str: ...


class PyMuPDFParser:
    def extract(self, pdf_bytes: bytes) -> str:
        import pymupdf

        with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
            # "blocks" sort mode handles two-column layout far better than the
            # default reading order, which interleaves columns line by line.
            pages = [page.get_text("text", sort=True) for page in doc]
        return clean(("\n".join(pages)))


def clean(text: str) -> str:
    text = _ARXIV_STAMP.sub("", text)
    # Rejoin words split across a line break by hyphenation.
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    text = _WHITESPACE.sub(" ", text)
    text = _BLANK_LINES.sub("\n\n", text)

    match = _REFERENCES.search(text)
    if match and match.start() > len(text) * 0.4:
        text = text[: match.start()]
    return text.strip()


def chunk(text: str, cfg: config.RetrievalConfig) -> list[str]:
    """Split into overlapping passages on paragraph boundaries.

    Sizes are approximated at 4 characters per token, which is close enough for
    chunking and avoids loading a tokenizer just to split text.
    """
    target = cfg.chunk_tokens * 4
    overlap = cfg.chunk_overlap * 4

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""

    for para in paragraphs:
        if current and len(current) + len(para) > target:
            chunks.append(current.strip())
            current = current[-overlap:] if overlap else ""
        current += "\n\n" + para

    if current.strip():
        chunks.append(current.strip())

    # Drop fragments too short to support a claim — usually stray headers.
    return [c for c in chunks if len(c) > 200]
