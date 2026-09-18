"""What the reader sees, and can change, about a course's sources before it is written.

Every poor section this project has produced traced to the corpus rather than
the writer: a query for "system design" that fetched a UI design system and a
polypill paper, a topic whose cached corpus had never been asked about
monitoring. The writer can only be as good as what retrieval hands it, and
until now the reader never saw that material until the notes were done.

`gather` fetches the corpus an outline needs and returns what it holds.
`add_url` lets the reader bring a page the adapters would never find.
Exclusion is not here at all: a struck document becomes a filter on
retrieval for that one course, because the topic corpus is shared with every
other reader of the subject and one person's junk is another's source.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx

from . import config, db, embedding, ingest, topics
from .models import Syllabus
from .parsing import PyMuPDFParser
from .parsing import chunk as split_text
from .pipeline import corpus_queries

_HEADERS = {"User-Agent": "notekit/0.1 (study-notes research prototype)"}


def gather(
    syllabus: Syllabus, *, namespace: str | None = None, limit: int = 10
) -> dict:
    """Make sure the corpus for this outline exists, then list it.

    For the reader's own uploads nothing is fetched. For a topic, this is the
    same ingest the course would have run, moved forward to where the reader
    can see the result: a cache hit returns at once, a new subject takes the
    minutes it takes, and either way the documents come back for review.
    """
    if namespace:
        with db.connect() as conn:
            return {"namespace": namespace, "documents": db.list_documents(conn, namespace)}

    resolved = topics.resolve(
        syllabus.topic_slug, label=syllabus.title or syllabus.summary
    ).namespace
    ingest.ingest_topic(
        slug=syllabus.topic_slug,
        query=corpus_queries(syllabus),
        namespace=resolved,
        limit=limit,
    )
    with db.connect() as conn:
        return {"namespace": resolved, "documents": db.list_documents(conn, resolved)}


class UnsafeUrl(ValueError):
    """The address is not one the server should fetch on a reader's behalf."""


def assert_public_url(url: str) -> str:
    """Refuse anything that is not a public http(s) host.

    The server fetches this address, so without the check a reader could point
    it at the database, the metadata service of whatever cloud it runs in, or
    anything else on the private network. Every address the name resolves to
    must be public. A name that resolves differently a moment later is not
    caught here, which is a known limit of resolving once.
    """
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise UnsafeUrl("Only http and https links can be added.")
    host = parsed.hostname
    if host == "localhost" or host.endswith(".localhost"):
        raise UnsafeUrl("That address is not public.")
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise UnsafeUrl(f"Could not resolve {host}.") from exc
    for info in infos:
        addr = ipaddress.ip_address(info[4][0])
        if not addr.is_global:
            raise UnsafeUrl("That address is not public.")
    return parsed.geturl()


class _Text(HTMLParser):
    """Visible text from HTML, with block boundaries kept as newlines."""

    _SKIP = {"script", "style", "noscript", "template", "svg"}
    _BLOCK = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "br", "tr", "section", "article"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            # Whitespace inside a text node, newlines included, is layout in
            # the source file, not structure. Only block tags make lines.
            self.parts.append(re.sub(r"\s+", " ", data))

    def text(self) -> str:
        raw = "".join(self.parts)
        lines = [" ".join(line.split()) for line in raw.splitlines()]
        return "\n".join(line for line in lines if line)


def html_to_text(html: str) -> tuple[str, str]:
    parser = _Text()
    parser.feed(html)
    return " ".join(parser.title.split()), parser.text()


def add_url(url: str, *, namespace: str, cfg: config.RetrievalConfig | None = None) -> dict:
    """Fetch one page or PDF and index it into the namespace.

    Returns the document as `list_documents` would. A link already indexed is
    returned rather than fetched again.
    """
    cfg = cfg or config.EMBEDDING
    safe = assert_public_url(url)

    with db.connect() as conn:
        existing = db.get_document_id(conn, namespace=namespace, source="url", external_id=safe)
        if existing is not None:
            row = next(d for d in db.list_documents(conn, namespace) if d["id"] == existing)
            return {**row, "already_indexed": True}

    with httpx.stream("GET", safe, headers=_HEADERS, timeout=20, follow_redirects=True) as res:
        res.raise_for_status()
        # Redirects can land somewhere the first check never saw.
        assert_public_url(str(res.url))
        body = b""
        for part in res.iter_bytes():
            body += part
            if len(body) > config.URL_FETCH_MAX_BYTES:
                raise UnsafeUrl(
                    f"That page is larger than {config.URL_FETCH_MAX_BYTES // (1024 * 1024)} MB."
                )
        content_type = res.headers.get("content-type", "")

    if "pdf" in content_type or safe.lower().endswith(".pdf"):
        text = PyMuPDFParser().extract(body)
        title = safe.rsplit("/", 1)[-1] or safe
    else:
        title, text = html_to_text(body.decode(res.encoding or "utf-8", errors="replace"))
        title = title or safe

    texts = split_text(text, cfg)
    if not texts:
        raise ValueError("That page had no readable text to index.")

    with db.connect() as conn:
        document_id = db.upsert_document(
            conn, namespace=namespace, source="url", external_id=safe, title=title[:200], url=safe
        )
        if document_id is None:
            raise ValueError("That link is already indexed.")
        db.insert_chunks(
            conn,
            document_id=document_id,
            namespace=namespace,
            texts=texts,
            embeddings=embedding.embed_documents(texts, cfg),
        )
        conn.commit()
        return {
            "id": document_id,
            "source": "url",
            "title": title[:200],
            "url": safe,
            "chunks": len(texts),
            "already_indexed": False,
        }
