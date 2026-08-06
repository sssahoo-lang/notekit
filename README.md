# Grounded course-notes agent

Turns a learning goal into a course of study notes written strictly from real
source material, with every claim cited back to the passage it came from.

## Status

| Milestone | State |
|---|---|
| 1. Core loop — ingest, retrieve, generate cited notes | working end to end |
| 2. Eval layer — faithfulness, coverage, refusal calibration | working; Langfuse tracing not yet wired |
| 3. Quiz generation | working; reuses the notes cache |
| 4. Upload adapter, per-user namespaces, style matching | working |
| 5. Open-domain routing | not started |
| 6. Next.js UI | working locally (`web/`) |
| 7. Deploy | not started |

## Measured results

Measured over a fixed syllabus (`fixtures/q-learning.json`, 4 modules, 12
learning goals) against a 13-document corpus drawn from Wikipedia and arXiv:

| Metric | Result |
|---|---|
| Faithfulness | **97–99%** (97.3% and 98.8% over two runs) |
| Refusal accuracy | **100%** (16/16 probe questions classified correctly) |
| Coverage | 42–67% — too noisy to quote as a single figure, see below |
| Cost per evaluated course | $0.22–0.38 |
| Cost per course with practice questions | $0.34 (was $0.66) |

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

Diagrams are measured too. Notes may include a Mermaid flowchart where the
passages describe a process or hierarchy, and every edge of one is an assertion
— so the evaluator converts each edge into a sentence ("Agent takes Action.",
"Environment leads to Reward.") and checks it for entailment alongside the
prose. Mermaid rather than a generated image for exactly this reason: the
source is text, so it can be read, cited and scored. A generated picture can be
confidently wrong with nothing to check it against.

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

# Build a course from your own files instead of open sources. No API key
# needed to index them; PDFs, .txt and .md are supported.
uv run notekit upload ~/Documents/lecture-notes --user sriya --topic ml
uv run notekit course "teach me how neural networks are trained" -n user-sriya-ml

# Save a syllabus as a fixture, so evaluation runs are comparable.
uv run notekit plan "teach me Q-learning" --save fixtures/q-learning.json

# Score a course for faithfulness and coverage. Repeat to see the spread.
uv run notekit eval --syllabus fixtures/q-learning.json --repeat 3 --explain

# Calibrate the refusal threshold. Needs no API key.
uv run notekit calibrate evalsets/q-learning.json
```

## Web UI

```bash
./scripts/dev.sh            # API on :8000 — checks the env, frees the port, starts postgres
cd web && cp .env.local.example .env.local && npm install && npm run dev
```

If anything misbehaves, `./scripts/doctor.sh` reports what is wrong and repairs
what it can. It exists because the editable install of `notekit` broke several
times during development — `ModuleNotFoundError: No module named 'notekit'` from
a virtualenv that had worked minutes earlier. The cause was never reproducible
on demand (concurrent `uv run`, `uv sync --reinstall-package`, and plain
reinstalls were each tried and none of them broke it), so `dev.sh` sets
`PYTHONPATH=src` and makes it not matter: imports work whether or not the `.pth`
survives, and `doctor.sh` reinstalls it for the `notekit` console script, which
has no such fallback.

Open [http://localhost:3000](http://localhost:3000). Course generation streams
over SSE; Upload and Style pages cover the milestone-4 surfaces. Details in
[`web/README.md`](web/README.md).

## HTTP API

```bash
uv run uvicorn notekit.api:app --reload --reload-dir src --port 8000
```

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | Liveness plus database connectivity |
| `GET /api/namespaces` | Indexed namespaces with document and chunk counts |
| `POST /api/course` | Generate a course, streamed as SSE; saves to history on completion |
| `GET /api/courses` · `GET/DELETE /api/courses/{id}` | Saved course history (by trust-based user id) |
| `POST /api/plan` | Plan a syllabus without generating |
| `GET /api/search` | Inspect what retrieval returns |
| `POST /api/upload` | Index uploaded files into a user namespace |
| `GET /api/style/{user}` · `POST /api/style/learn` | Read and learn style profiles |
| `POST /api/calibrate` | Run a refusal calibration set |

`POST /api/course` streams modules as each one completes, so the reader can
start on the first while the rest are still being written. Events arrive out of
order — whichever module finishes first is sent first — and each carries an
`index` for the client to place it by. Event types: `planning`, `syllabus`,
`ingesting`, `ingested`, `module`, `module_error`, `done`, `error`. A failure
mid-stream arrives as an `error` event rather than an HTTP status, since the
headers are long gone by then.

Notes stream token by token via `token` events, and each module also emits a
terminal `module` event carrying the complete object with citations and quiz. A
client renders tokens as they land and swaps in the final object when it
arrives.

Modules stream as coroutines on one event loop, not as worker threads. That
distinction is worth 2.8x on time-to-first-prose:

| | Threads | Async |
|---|---|---|
| First prose | 52.3s | **18.4s** |
| Stagger between modules' first tokens | ~35s | **7.6s** |
| Whole course, four modules | 82.8s | **41.2s** |

Streaming is I/O-bound, but parsing its SSE frames is Python work. Four threads
each parsing their own stream contended on the GIL and staggered each other's
first token by tens of seconds; coroutines on one loop do not contend. Retrieval
stays on a thread via `asyncio.to_thread`, because that genuinely is CPU-bound
torch work and would otherwise block every other module's stream.

Getting there meant measuring rather than guessing. Retrieval was not the cause
(all four modules retrieve in 3.9s), and neither was the API (four raw
concurrent streams reach first token in 0.76–2.33s). Two things were: thread
contention, and `MAX_TOKENS_NOTES = 4000` — given room for 4,000 tokens the
model writes about 5,800 characters, and a single module takes 37s to generate
against 8.7s at `max_tokens=700`. Most of the remaining wait is the notes being
long, not anything being slow.

Two levers remain, both unmeasured for quality impact: lowering
`MAX_TOKENS_NOTES` shortens notes and wait proportionally, and
`config.GENERATION_THINKING = {"type": "disabled"}` cuts time-to-first-text from
2.9s to 0.9s. Either changes the generation path and needs faithfulness
re-measured against the fixture.

Deltas are coarse: roughly 114 characters per event rather than per-token.

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

## Style-matched notes, and what they cost

Learn how someone writes from any sample, then generate any course in that
voice — over their uploaded files, arXiv, or Wikipedia. Style is a per-user
property, independent of the corpus:

```bash
uv run notekit style learn ~/my-writing.md --user sriya
uv run notekit course "teach me Q-learning" --user sriya
```

Style transfers well. A profile learned from casual writing about databases
produced Q-learning notes opening "So let's start with the big picture",
explaining the field through learning to ride a bike and the
exploration-exploitation trade-off through choosing ice cream flavours — in
second person, with inline citations intact, and with no database subject matter
carried across.

**It costs about 10 points of faithfulness.** Measured over the same fixed
syllabus, two runs each:

| Voice | Faithfulness | Claims per course |
|---|---|---|
| Default | 97.3%, 98.8% | 143, 169 |
| Learned style | 89.5%, 85.5% | 86, 83 |

That gap is far outside the ~1.5-point run-to-run noise, so it is a real effect
rather than variance. Inspecting the unsupported claims shows two causes:

1. **Genuinely unsourced facts.** Reaching for familiar comparisons pulls in
   outside knowledge — "in classical planning, the model is already known", "the
   multi-armed bandit problem formalises..." — that no passage supplied. This is
   a true grounding failure and the reason the feature is not on by default.
2. **Rhetorical framing scored as assertion.** "Exploration is the cost required
   to learn" is a framing device, not a claim about the subject, but the claim
   extractor cannot tell the difference. Part of the 10 points is measurement
   artefact rather than hallucination.

Separating those two would need the claim extractor to distinguish illustrative
from assertive sentences. Until then the honest statement is that personalised
notes are measurably less grounded, by an amount whose upper bound is 10 points.

The profile itself is safe by construction: it describes form only — sentence
rhythm, register, structure, habits of expression — and is verified to contain
no subject matter from the sample. The sample is never stored and never sent at
generation time. Pasting raw notes in as a style exemplar would put
content-shaped text beside the retrieved passages, and the model would assert
from it.

One boundary is deliberate. Matching how someone *writes* is in scope. Matching
how someone *understands* is not: student notes often contain misconceptions,
and mirroring them would reinforce errors while citing correct sources —
grounded-looking and wrong. Difficulty is controlled by the level in the
learning goal, independently of style.

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
- **Uploads are isolated, but not access-controlled.** Each user's files go into
  their own namespace and retrieval cannot cross namespaces, which is verified:
  querying one user's namespace never returns another's chunks. But there is no
  auth, so `--user` is taken on trust. Anyone who can run the CLI can name any
  user id. This is isolation, not security, and it needs real authentication
  before the system is exposed to more than one person.
- Scanned or image-only PDFs are rejected with a clear message rather than
  indexed empty. OCR is not wired up yet.
- PDF parsing is a first pass (`PyMuPDFParser`). It strips reference sections and
  rejoins hyphenated line breaks, but inline math and table content survive as
  noisy text. The parser sits behind a Protocol so it can be replaced without
  touching retrieval or generation.
