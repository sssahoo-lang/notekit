# Grounded course-notes agent

Turns a learning goal into a course of study notes written strictly from real
source material, with every claim cited back to the passage it came from.

> Milestone 1 of 7. The headline faithfulness numbers land in milestone 2; this
> README gets rewritten around them then.

## Status

| Milestone | State |
|---|---|
| 1. Core loop — ingest, retrieve, generate cited notes | working end to end |
| 2. Eval layer — faithfulness, coverage, refusal calibration | working; Langfuse tracing not yet wired |
| 3. Quiz generation | not started |
| 4. Upload adapter | not started |
| 5. Open-domain routing | not started |
| 6. Next.js UI | not started |
| 7. Deploy | not started |

## Measured results

One course on Q-learning, five modules, over a corpus of 13 documents drawn from
Wikipedia and arXiv:

| Metric | Result |
|---|---|
| Faithfulness | **97.4%** (187/192 claims entailed by their retrieved passages) |
| Coverage | **83.3%** of stated learning goals addressed |
| Refusal accuracy | **100%** (16/16 probe questions classified correctly) |
| Cost per evaluated course | $0.38 |

Retrieving once per learning goal rather than once per module, and building the
corpus from module queries rather than the topic name, moved coverage from 60.0%
to 83.3% and faithfulness from 95.7% to 97.4% at unchanged cost. That comparison
is suggestive rather than controlled: the planner emits a different syllabus on
each run, so the two measurements are not over identical work. Pinning a fixed
syllabus for evaluation runs is the next fix, and a precondition for trusting
any future before/after number.

Refusal is calibrated rather than guessed. Questions the corpus covers rerank at
+0.28 to +8.50; questions it does not (French Revolution, sourdough
fermentation, Honda timing belts) score −3.54 to −11.01. The gap is clean, and
the threshold sits inside it:

```bash
uv run notekit calibrate evalsets/q-learning.json
```

Two caveats worth stating plainly. Faithfulness is judged by Haiku against notes
written by Sonnet — same model family, so the grader shares blind spots with the
writer, and the number should be read as a regression signal rather than an
absolute. And these are single-run figures on one topic; there is no variance
estimate yet.

Coverage remains the weaker number. Two modules still address only two of three
learning goals, and the honest reading is that some goals simply have no
supporting material in a 13-document corpus — which is the system behaving
correctly, not failing.

## Setup

Requires Python 3.11+, Docker, and [uv](https://docs.astral.sh/uv/).

```bash
docker compose up -d          # Postgres 16 + pgvector on port 5433
uv sync                       # installs deps into .venv
cp .env.example .env          # then add your ANTHROPIC_API_KEY
```

Embeddings (`bge-small-en-v1.5`) and reranking (`ms-marco-MiniLM-L-6-v2`) run
locally, so `ANTHROPIC_API_KEY` is the only secret. The first run downloads
about 220MB of model weights.

## Usage

```bash
# Fetch and index a corpus. Needs no API key.
uv run notekit ingest "q-learning" --limit 10

# Inspect what retrieval returns. Needs no API key.
uv run notekit search "how does the Bellman equation define the Q function" -n q-learning

# Plan a syllabus and write cited notes. Needs the API key.
uv run notekit course "teach me Q-learning at an intermediate level"

uv run notekit stats q-learning

# Score a generated course for faithfulness and coverage.
uv run notekit eval "teach me Q-learning at an intermediate level" --explain

# Calibrate the refusal threshold. Needs no API key.
uv run notekit calibrate evalsets/q-learning.json
```

## How it works

Three lanes, separated by whether they are allowed to block the user:

- **Cold lane** (`ingest.py`, `adapters/`, `parsing.py`) — fetch, parse, chunk,
  embed, store. Runs once per topic; every later course on that topic is a cache
  hit. Never on the critical path.
- **Hot lane** (`pipeline.py`, `retrieval.py`) — plan the syllabus, then for each
  module retrieve, rerank, and generate cited notes. Modules run concurrently,
  which is the single biggest latency lever in the project.
- **Side lane** (milestone 2) — faithfulness and coverage scoring. Runs after
  generation returns and never gates the response.

Configuration — model tiers, chunking, retrieval parameters, the refusal
threshold — lives in `src/notekit/config.py`.

## Known limitations

- **arXiv alone is a poor corpus for foundational material.** It indexes the
  research frontier, not pedagogy: a request to teach Q-learning fundamentals
  retrieves papers on continuous-time mean-field extensions, and the system
  correctly refuses most modules. Teaching basics needs an encyclopaedic or
  textbook adapter (Wikipedia, OpenStax) alongside arXiv, which moves part of
  milestone 5 forward into the core.
- Ingestion is keyed on the topic slug, but each module carries its own
  retrieval query. Building the corpus from the module queries rather than the
  topic alone would materially improve coverage.
- The refusal threshold in `config.py` is a placeholder, though early evidence
  puts it in roughly the right place: covered queries rerank at +3.7 to +6.6 and
  uncovered ones at −4.7 to −5.3, against a threshold of −2.0. Milestone 2 must
  still calibrate it properly against deliberate out-of-corpus questions.
- Topic canonicalisation relies on the planner emitting a consistent slug. Close
  variants may still fragment the corpus across namespaces.
- Single-user. There is no auth and no per-user namespace isolation yet; that
  arrives with the upload adapter in milestone 4.
- PDF parsing is a first pass (`PyMuPDFParser`). It strips reference sections and
  rejoins hyphenated line breaks, but inline math and table content survive as
  noisy text. The parser sits behind a Protocol so it can be replaced without
  touching retrieval or generation.
