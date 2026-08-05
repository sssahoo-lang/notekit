"""Every tunable choice in one place.

The model tiers below are the main cost lever. Generation runs on Sonnet 5;
planning and evaluation run on Haiku 4.5, which is where most of the token
volume lives. Point GENERATION_MODEL at "claude-opus-5" if you want maximum
quality for a demo — it roughly triples the per-course cost.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

# --- Models -----------------------------------------------------------------

# Writes the cited notes. The quality-sensitive call.
GENERATION_MODEL = "claude-sonnet-5"

# Syllabus planning and topic canonicalisation: structured, low-judgement work.
PLANNER_MODEL = "claude-haiku-4-5"

# Answering "what does this mean?" about a highlighted span. Short, narrow, and
# grounded in passages already retrieved, so it does not need the strong model.
EXPLAIN_MODEL = "claude-haiku-4-5"

# LLM-as-judge for faithfulness and coverage. Highest token volume in the
# project, lowest judgement difficulty — keep it cheap.
JUDGE_MODEL = "claude-haiku-4-5"

# Sonnet 5 thinks before answering by default. Thinking happens before any text
# is emitted, so it sets the floor on time-to-first-token when streaming:
# measured at 2.9s with thinking on versus 0.9s with it off, and it grows with
# prompt complexity. Set to {"type": "disabled"} to trade some reasoning for a
# faster first paint — and re-measure faithfulness against the fixture if you do,
# since it changes the generation path.
GENERATION_THINKING: dict | None = None

MAX_TOKENS_NOTES = 4000
MAX_TOKENS_PLAN = 2000
MAX_TOKENS_QUIZ = 3000
MAX_TOKENS_EXPLAIN = 800

# Published rates, USD per million tokens. Used only for the cost estimate the
# CLI prints; nothing depends on these being exact.
PRICING = {
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
}

# --- Embedding and retrieval ------------------------------------------------


@dataclass(frozen=True)
class RetrievalConfig:
    """One point in the config sweep that milestone 2 will evaluate."""

    name: str
    embedding_model: str
    chunk_tokens: int
    chunk_overlap: int
    dense_k: int
    sparse_k: int
    rerank_to: int
    rerank_model: str | None


# Changing embedding_model means changing the vector(384) column in
# scripts/schema.sql and re-ingesting. bge-small is 384 dims; bge-base is 768.
EMBEDDING = RetrievalConfig(
    name="baseline",
    embedding_model="BAAI/bge-small-en-v1.5",
    chunk_tokens=400,
    chunk_overlap=60,
    dense_k=20,
    sparse_k=20,
    rerank_to=8,
    rerank_model="cross-encoder/ms-marco-MiniLM-L-6-v2",
)

# Milestone 2 sweeps these four and reports faithfulness for each.
SWEEP = [
    EMBEDDING,
    RetrievalConfig("no-rerank", "BAAI/bge-small-en-v1.5", 400, 60, 20, 20, 8, None),
    RetrievalConfig("dense-only", "BAAI/bge-small-en-v1.5", 400, 60, 20, 0, 8,
                    "cross-encoder/ms-marco-MiniLM-L-6-v2"),
    RetrievalConfig("large-chunks", "BAAI/bge-small-en-v1.5", 800, 100, 20, 20, 8,
                    "cross-encoder/ms-marco-MiniLM-L-6-v2"),
]

# --- Refusal ----------------------------------------------------------------

# If the best reranked chunk scores below this, the module is reported as
# uncovered rather than written. This number is a placeholder: it cannot be
# chosen sensibly until milestone 2 measures real scores against deliberately
# out-of-corpus questions. Treat it as unvalidated.
REFUSAL_SCORE_THRESHOLD = -2.0

# --- Infrastructure ---------------------------------------------------------

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://notekit:notekit@localhost:5433/notekit"
)

MAX_PARALLEL_MODULES = 4

# A module retrieves once for its own query and once per learning goal, then
# merges the results. This caps the merged set: more context raises coverage but
# costs input tokens and dilutes the reranked ordering.
MAX_CONTEXT_CHUNKS = 14
