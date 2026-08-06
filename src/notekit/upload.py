"""Ingesting a user's own files into an isolated namespace.

The same core engine serves this and the open-domain adapters: files become
chunks in a namespace, and retrieval and generation never learn where they came
from. What differs is isolation — uploaded material is private, so it goes into
a namespace no other user's course can retrieve from.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from . import config, db, embedding
from .identity import ANONYMOUS, normalize
from .parsing import PyMuPDFParser, chunk as split

SUPPORTED = {".pdf", ".txt", ".md", ".markdown"}

_parser = PyMuPDFParser()


class UnsupportedFile(Exception):
    pass


def user_namespace(user_id: str, topic: str = "notes") -> str:
    """Namespace uploads per user so one person's files cannot leak into
    another's course. There is no auth yet, so `user_id` is taken on trust —
    this is isolation, not access control, and the README says so."""
    safe_user = normalize(user_id)
    safe_topic = normalize(topic)
    if safe_user == ANONYMOUS and not (user_id or "").strip():
        raise ValueError("user_id must contain at least one alphanumeric character")
    return f"user-{safe_user}-{safe_topic}"


def content_hash(data: bytes) -> str:
    """Stable id for file bytes — survives temp-path uploads and renames."""
    return hashlib.sha256(data).hexdigest()


def extract(path: Path) -> str:
    """Read one file to plain text, or say clearly why it cannot be read."""
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED:
        raise UnsupportedFile(
            f"{path.name}: {suffix or 'no extension'} is not supported "
            f"(supported: {', '.join(sorted(SUPPORTED))})"
        )

    if suffix == ".pdf":
        try:
            text = _parser.extract(path.read_bytes())
        except Exception as exc:  # noqa: BLE001
            raise UnsupportedFile(f"{path.name}: could not be parsed ({exc})") from exc
        if len(text.strip()) < 200:
            # Almost certainly a scanned document. OCR is not wired up yet, so
            # say that plainly rather than indexing an empty file.
            raise UnsupportedFile(
                f"{path.name}: almost no extractable text. If this is a scanned "
                "PDF it needs OCR, which is not supported yet."
            )
        return text

    return path.read_text(encoding="utf-8", errors="replace")


def collect(paths: list[str]) -> list[Path]:
    """Expand directories into their supported files."""
    files: list[Path] = []
    for raw in paths:
        path = Path(raw).expanduser()
        if path.is_dir():
            files.extend(
                sorted(p for p in path.rglob("*") if p.suffix.lower() in SUPPORTED)
            )
        elif path.exists():
            files.append(path)
        else:
            raise FileNotFoundError(f"{raw}: no such file or directory")
    return files


def ingest_files(
    paths: list[str],
    *,
    namespace: str,
    cfg: config.RetrievalConfig | None = None,
) -> dict:
    """Parse, chunk, embed and store local files. Returns a summary dict.

    Documents are keyed by content hash, not filesystem path, so the same PDF
    uploaded twice through the API temp directory is recognised as one document.
    """
    cfg = cfg or config.EMBEDDING
    files = collect(paths)
    if not files:
        return {
            "files": 0,
            "skipped": [],
            "new_documents": 0,
            "updated_documents": 0,
            "new_chunks": 0,
        }

    skipped: list[str] = []
    new_documents = 0
    updated_documents = 0
    total_chunks = 0
    # Identical content seen twice in one batch (common with temp copies).
    seen_hashes: set[str] = set()

    with db.connect() as conn:
        for path in files:
            try:
                raw = path.read_bytes()
                digest = content_hash(raw)
                text = extract(path)
            except UnsupportedFile as exc:
                # One bad file must not abort an upload of fifty.
                skipped.append(str(exc))
                continue

            if digest in seen_hashes:
                skipped.append(f"{path.name}: duplicate of another file in this upload")
                continue
            seen_hashes.add(digest)

            document_id, created = db.upsert_or_replace_document(
                conn,
                namespace=namespace,
                source="upload",
                external_id=digest,
                title=path.stem,
                url=f"file://{path.name}",
            )

            existing_chunks = conn.execute(
                "SELECT count(*) AS n FROM chunks WHERE document_id = %s",
                (document_id,),
            ).fetchone()["n"]

            if not created and int(existing_chunks) > 0:
                # Same content hash already indexed — keep existing chunks.
                # (Hash is of file bytes, so content cannot have changed.)
                skipped.append(f"{path.name}: already indexed in this namespace")
                continue

            texts = split(text, cfg)
            if not texts:
                skipped.append(f"{path.name}: no chunks survived splitting")
                continue

            vectors = embedding.embed_documents(texts, cfg)
            if created:
                db.insert_chunks(
                    conn,
                    document_id=document_id,
                    namespace=namespace,
                    texts=texts,
                    embeddings=vectors,
                )
                new_documents += 1
            else:
                # Row existed but had no chunks (interrupted prior upload).
                db.replace_chunks(
                    conn,
                    document_id=document_id,
                    namespace=namespace,
                    texts=texts,
                    embeddings=vectors,
                )
                updated_documents += 1
            total_chunks += len(texts)
            print(f"  + {path.name} ({len(texts)} chunks)")

        stats = db.namespace_stats(conn, namespace)
        if int(stats["chunks"] or 0) > 0:
            db.mark_topic_ingested(conn, namespace, namespace, "user upload")
        conn.commit()

    return {
        "files": len(files),
        "skipped": skipped,
        "new_documents": new_documents,
        "updated_documents": updated_documents,
        "new_chunks": total_chunks,
        **stats,
    }
