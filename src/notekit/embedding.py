"""Local embedding and reranking.

Both models run on-device, so the retrieval config sweep in milestone 2 costs
nothing per run and the project needs only one API key. First call downloads
the weights (~130MB for bge-small, ~90MB for the cross-encoder).
"""

from __future__ import annotations

import functools
import os
import threading

from . import config

# Set before torch imports. Without it, tokenizers forks inside our thread pool
# and warns (or deadlocks) on macOS.
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

# Torch is not thread-safe here for either construction or inference — four
# module threads hitting it concurrently segfaults the interpreter on macOS.
# One lock guards both.
#
# This serialises retrieval across modules, which costs little: a query embed
# plus a rerank of ~40 pairs is well under a second, while the generation call
# it feeds is tens of seconds. The parallelism that matters — the Claude API
# calls — is untouched.
_load_lock = threading.Lock()


@functools.lru_cache(maxsize=4)
def _encoder_uncached(name: str):
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(name)


@functools.lru_cache(maxsize=4)
def _reranker_uncached(name: str):
    from sentence_transformers import CrossEncoder

    return CrossEncoder(name)


def _encoder(name: str):
    with _load_lock:
        return _encoder_uncached(name)


def _reranker(name: str):
    with _load_lock:
        return _reranker_uncached(name)


def warm(cfg: config.RetrievalConfig) -> None:
    """Load models on the main thread before any concurrent work starts."""
    _encoder(cfg.embedding_model)
    if cfg.rerank_model:
        _reranker(cfg.rerank_model)


def embed_documents(texts: list[str], cfg: config.RetrievalConfig) -> list[list[float]]:
    model = _encoder(cfg.embedding_model)
    with _load_lock:
        vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return [v.tolist() for v in vectors]


def embed_query(text: str, cfg: config.RetrievalConfig) -> list[float]:
    # bge models expect an instruction prefix on the query side only.
    prefixed = f"Represent this sentence for searching relevant passages: {text}"
    model = _encoder(cfg.embedding_model)
    with _load_lock:
        return model.encode(prefixed, normalize_embeddings=True).tolist()


def rerank(query: str, passages: list[str], cfg: config.RetrievalConfig) -> list[float]:
    """Cross-encoder relevance scores, one per passage. Higher is better.

    Scores are unbounded logits, not probabilities — that is why
    REFUSAL_SCORE_THRESHOLD is a negative number and needs calibrating.
    """
    if not cfg.rerank_model or not passages:
        return [0.0] * len(passages)
    model = _reranker(cfg.rerank_model)
    with _load_lock:
        scores = model.predict([(query, p) for p in passages], show_progress_bar=False)
    return [float(s) for s in scores]
