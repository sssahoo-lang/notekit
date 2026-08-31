"""PDF text extraction and chunking.

Research-paper PDFs are the messiest input in the project: two-column layout,
inline math, running headers, and a reference section that is pure retrieval
noise. `PyMuPDFParser` is a first pass, deliberately behind a Protocol so it can
be swapped for a LaTeX-source or layout-aware parser without touching ingestion.

Chunking prefers section boundaries (wiki / markdown / numbered headings), then
packs paragraphs to the embedding tokenizer's token budget.
"""

from __future__ import annotations

import re
from typing import Protocol

from . import config, embedding

# Everything from a references heading to the end of the document is dropped:
# citations match well against almost any query and crowd out real content.
_REFERENCES = re.compile(
    r"\n\s*(references|bibliography)\s*\n", re.IGNORECASE
)
_ARXIV_STAMP = re.compile(r"arXiv:\d{4}\.\d{4,5}v\d+\s+\[[^\]]+\]\s+\d+\s+\w+\s+\d{4}")
_WHITESPACE = re.compile(r"[ \t]+")
_BLANK_LINES = re.compile(r"\n{3,}")

# Section starts: markdown headings, wiki ==headings==, numbered titles, CAPS lines.
_SECTION_HEADING = re.compile(
    r"(?m)^(?:"
    r"\#{1,3}\s+\S[^\n]{2,120}$|"
    r"={2,}\s*[^=\n]{3,100}\s*={2,}\s*$|"
    r"\d+(?:\.\d+){0,3}\.?\s+[A-Z][^\n]{3,100}$|"
    r"[A-Z][A-Z0-9][A-Z0-9 ,/&:\-]{6,80}$"
    r")"
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'])")


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


def _split_sections(text: str) -> list[str]:
    """Break a document into heading-led sections when headings are present."""
    matches = list(_SECTION_HEADING.finditer(text))
    if len(matches) < 2:
        return [text.strip()] if text.strip() else []

    sections: list[str] = []
    # Keep any preface before the first heading with that heading's section.
    first = matches[0].start()
    if first > 0 and text[:first].strip():
        # Attach preface to the first headed section.
        pass

    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        if i == 0 and first > 0:
            piece = text[:end].strip()
        else:
            piece = text[start:end].strip()
        if piece:
            sections.append(piece)
    return sections or ([text.strip()] if text.strip() else [])


def _pack_units(
    units: list[str],
    *,
    cfg: config.RetrievalConfig,
    target: int,
    overlap: int,
) -> list[str]:
    """Greedy pack of text units to a token budget with token overlap."""
    chunks: list[str] = []
    current_parts: list[str] = []
    current_tokens = 0

    def flush() -> None:
        nonlocal current_parts, current_tokens
        if not current_parts:
            return
        text = "\n\n".join(current_parts).strip()
        if text:
            chunks.append(text)
        if overlap > 0 and text:
            # Keep a trailing overlap window for the next chunk.
            words = text.split()
            # Approximate overlap by words, then trim to token budget.
            keep = words[-max(20, overlap // 2) :]
            overlap_text = " ".join(keep)
            while keep and embedding.count_tokens(overlap_text, cfg) > overlap:
                keep = keep[1:]
                overlap_text = " ".join(keep)
            current_parts = [overlap_text] if overlap_text else []
            current_tokens = (
                embedding.count_tokens(overlap_text, cfg) if overlap_text else 0
            )
        else:
            current_parts = []
            current_tokens = 0

    for unit in units:
        unit = unit.strip()
        if not unit:
            continue
        unit_tokens = embedding.count_tokens(unit, cfg)

        if unit_tokens > target:
            # Flush what we have, then split oversized units on sentences.
            flush()
            sentences = _SENTENCE_SPLIT.split(unit)
            if len(sentences) <= 1:
                chunks.append(unit)
                current_parts = []
                current_tokens = 0
                continue
            for sentence in sentences:
                st = embedding.count_tokens(sentence, cfg)
                if current_parts and current_tokens + st > target:
                    flush()
                current_parts.append(sentence)
                current_tokens += st
            continue

        if current_parts and current_tokens + unit_tokens > target:
            flush()
        current_parts.append(unit)
        current_tokens += unit_tokens

    flush()
    return chunks


def chunk(text: str, cfg: config.RetrievalConfig) -> list[str]:
    """Split into overlapping passages on section, then paragraph, boundaries.

    Sizes use the embedding model's tokenizer so chunk_tokens matches retrieval.
    """
    target = cfg.chunk_tokens
    overlap = cfg.chunk_overlap
    min_tokens = config.MIN_CHUNK_TOKENS

    sections = _split_sections(text)
    chunks: list[str] = []

    for section in sections:
        paragraphs = [p.strip() for p in section.split("\n\n") if p.strip()]
        if not paragraphs:
            continue
        # Prefer packing the whole section when it already fits.
        section_tokens = embedding.count_tokens(section, cfg)
        if section_tokens <= target and section_tokens >= min_tokens:
            chunks.append(section.strip())
            continue
        chunks.extend(
            _pack_units(paragraphs, cfg=cfg, target=target, overlap=overlap)
        )

    # Drop fragments too short to support a claim, usually stray headers.
    kept: list[str] = []
    for c in chunks:
        if embedding.count_tokens(c, cfg) >= min_tokens:
            kept.append(c)
    return kept
