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

Measured over a fixed syllabus (`fixtures/q-learning.json`, 4 modules, 12
learning goals) against a 13-document corpus drawn from Wikipedia and arXiv:

| Metric | Result |
|---|---|
| Faithfulness | **97–99%** (97.3% and 98.8% over two runs) |
| Refusal accuracy | **100%** (16/16 probe questions classified correctly) |
| Coverage | 42–67% — too noisy to quote as a single figure, see below |
| Cost per evaluated course | $0.22–0.38 |

**Coverage is not yet a trustworthy metric.** Two runs of the *same* fixed
syllabus returned 41.7% and 66.7% — a 25-point swing with nothing changed.
There are only 12 learning goals in the fixture, so each is worth 8.3 points,
and the judge is not deterministic. Any single coverage number from this system
is noise at that scale, and `notekit eval --repeat N` exists to make that
visible rather than hide it.

This retracts an earlier claim in this README that per-goal retrieval lifted
coverage from 60% to 83%. Those two measurements came from different
planner-generated syllabi, and the run-to-run variance turns out to be as large
as the effect. The change is still defensible on mechanism — generation can only
address a goal if retrieval surfaced material for it — but it has not been
measured, and it is not counted as a result here.

Faithfulness is stable across runs and is the number this project stands on.

Refusal is calibrated rather than guessed. Questions the corpus covers rerank at
+0.28 to +8.50; questions it does not (French Revolution, sourdough
fermentation, Honda timing belts) score −3.54 to −11.01. The gap is clean, and
the threshold sits inside it:

```bash
uv run notekit calibrate evalsets/q-learning.json
```

One caveat applies to every number above: faithfulness is judged by Haiku
against notes written by Sonnet. Same model family, so the grader shares blind
spots with the writer, and the figure is better read as a regression signal than
as ground truth. An independent judge — a different provider, or spot-checking
by hand against a labelled set — is the way to establish that properly.

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

# Save a syllabus as a fixture, so evaluation runs are comparable.
uv run notekit plan "teach me Q-learning" --save fixtures/q-learning.json

# Score a course for faithfulness and coverage. Repeat to see the spread.
uv run notekit eval --syllabus fixtures/q-learning.json --repeat 3 --explain

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
