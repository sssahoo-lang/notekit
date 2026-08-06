"""Hot lane: the only work a user waits on.

The functions below are written as discrete nodes over an explicit state dict so
they map onto a LangGraph `StateGraph` without restructuring: `plan_syllabus` is
the entry node, `generate_module_notes` is the per-module loop body, and
`run_course` is the executor. Milestone 1 runs them with a thread pool; swapping
in LangGraph is a wiring change once re-planning gives the graph something to
decide.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor

from . import config, embedding, ingest, llm, retrieval
from .models import Chunk, Module, ModuleNotes, Quiz, QuizQuestion, Syllabus
from .style import StyleProfile

_CITATION = re.compile(r"\[c(\d+)\]")
_REFUSAL_MARKER = "INSUFFICIENT"

_PLANNER_SYSTEM = """You design short, focused courses of study.

Given a learning goal, produce a syllabus of 3-5 modules that build on each \
other. Each module needs a retrieval query written to match the language of \
academic source material, not the language of the learner's question.

The topic_slug must be canonical: expand abbreviations to their full form so \
that different phrasings of the same subject produce an identical slug."""

# Shared by the notes and quiz calls. Both must send an identical prefix —
# system text plus the cached passages block — or the quiz call cannot read the
# cache the notes call wrote. Task-specific instructions therefore live in the
# user turn, after the cached block, not here.
_GROUNDING_SYSTEM = """You work strictly from provided source passages.

Rules, in order of importance:

1. Every factual claim must be supported by one of the numbered passages. If \
the passages do not support a claim, do not make it.
2. Cite the passage each claim came from inline, as [c123], using the exact \
passage id. Multiple citations per sentence are fine.
3. If the passages do not cover enough of the module topic, reply with exactly \
one line: the word INSUFFICIENT, then one sentence naming what is missing. \
Write nothing else. Refusing cleanly is the correct answer, not a fallback.
4. Do not use outside knowledge, even where you are confident it is correct.

The user turn states which task to perform."""

_NOTES_TASK = """Write the study notes for this module.

Address every stated learning goal that the passages support, in order. Where \
the passages support a goal only partly, cover what they do support and say \
briefly what is missing. Do not skip a goal in silence.

Write for an intermediate learner: prose with short paragraphs, no headings, \
no preamble, no closing summary."""

_QUIZ_TASK = """Write {n} multiple-choice questions testing this module.

Each question needs exactly four options and one correct answer, derivable \
from the passages alone. Wrong options must be plausible but clearly wrong \
given the passages, never true-but-unmentioned.

Answer in exactly this format, nothing else:

Q: <question>
A) <option>
B) <option>
C) <option>
D) <option>
ANSWER: <A, B, C or D>
WHY: <one or two sentences, citing passages as [c123]>

Repeat that block for each question, separated by a blank line."""

# Deliberately parsed from plain text rather than requested as structured
# output. Structured output injects a schema ahead of the cached passages,
# changing the request prefix, so the quiz call re-paid full price for context
# the notes call had just sent. Parsing a fixed layout keeps the prefix
# identical and the passages come back from cache. `parse_quiz` returns None on
# anything unexpected, and the caller falls back to the structured path.
_QUIZ_BLOCK = re.compile(
    r"Q:\s*(?P<q>.+?)\n\s*A\)\s*(?P<a>.+?)\n\s*B\)\s*(?P<b>.+?)\n\s*C\)\s*"
    r"(?P<c>.+?)\n\s*D\)\s*(?P<d>.+?)\n\s*ANSWER:\s*(?P<ans>[ABCD])\b\s*"
    r"(?:\n\s*WHY:\s*(?P<why>.+?))?(?=\n\s*Q:|\Z)",
    re.DOTALL | re.IGNORECASE,
)


def parse_quiz(text: str) -> Quiz | None:
    """Read the fixed question layout. None when it does not match."""
    questions: list[QuizQuestion] = []
    for m in _QUIZ_BLOCK.finditer(text):
        options = [m.group(k).strip() for k in ("a", "b", "c", "d")]
        if any(not o for o in options):
            return None
        questions.append(
            QuizQuestion(
                question=m.group("q").strip(),
                options=options,
                answer_index="ABCD".index(m.group("ans").upper()),
                explanation=(m.group("why") or "").strip(),
            )
        )
    return Quiz(questions=questions) if questions else None


def plan_syllabus(goal: str) -> Syllabus:
    """Entry node. One structured call — canonical slug plus module breakdown."""
    return llm.parse(
        model=config.PLANNER_MODEL,
        system=_PLANNER_SYSTEM,
        prompt=f"Learning goal: {goal}",
        max_tokens=config.MAX_TOKENS_PLAN,
        schema=Syllabus,
    )


def _format_passages(chunks: list[Chunk]) -> str:
    return "\n\n".join(
        f"[{c.citation_key}] (from: {c.document_title})\n{c.text}" for c in chunks
    )


def _refusal_for(module: Module, chunks: list[Chunk]) -> ModuleNotes | None:
    """Pre-generation refusal checks, shared by the streaming and plain paths."""
    if not chunks:
        return ModuleNotes(
            module_title=module.title,
            body="",
            cited_chunk_ids=[],
            chunks=[],
            refused=True,
            refusal_reason="No source passages retrieved for this module.",
        )
    if chunks[0].score < config.REFUSAL_SCORE_THRESHOLD:
        return ModuleNotes(
            module_title=module.title,
            body="",
            cited_chunk_ids=[],
            chunks=chunks,
            refused=True,
            refusal_reason=(
                f"Best passage scored {chunks[0].score:.2f}, below the coverage "
                f"threshold of {config.REFUSAL_SCORE_THRESHOLD}."
            ),
        )
    return None


def generate_module_notes(
    module: Module,
    *,
    namespace: str,
    cfg: config.RetrievalConfig | None = None,
    with_quiz: bool = False,
    style: StyleProfile | None = None,
) -> ModuleNotes:
    """Per-module loop body: retrieve, rerank, generate cited notes."""
    cfg = cfg or config.EMBEDDING
    # Retrieve for the module query and for each learning goal. Retrieving only
    # on the module query gave notes that were faithful but addressed barely
    # half the stated goals, because generation can only cover what it is shown.
    chunks = retrieval.retrieve_multi(
        [module.query, *module.learning_goals], namespace=namespace, cfg=cfg
    )

    refusal = _refusal_for(module, chunks)
    if refusal:
        return refusal

    goals = "\n".join(f"- {g}" for g in module.learning_goals)
    # Identical string in both calls: the quiz call can only read this from
    # cache if the notes call wrote exactly it.
    passages = f"Source passages:\n\n{_format_passages(chunks)}"

    # Style guidance goes last, after the grounding rules and the task, so it
    # reads as a modifier on how to write rather than as a competing brief.
    style_instruction = f"\n\n{style.as_instruction()}" if style else ""

    body = llm.complete(
        model=config.GENERATION_MODEL,
        system=_GROUNDING_SYSTEM,
        cached_prefix=passages,
        prompt=(
            f"Module: {module.title}\n\n"
            f"The reader should come away able to:\n{goals}\n\n"
            f"{_NOTES_TASK}{style_instruction}"
        ),
        max_tokens=config.MAX_TOKENS_NOTES,
    )

    if body.strip().startswith(_REFUSAL_MARKER):
        # Keep only the first line: the model sometimes ignores rule 3 and
        # appends partial notes anyway, which must not be reported as a reason.
        reason = body.strip().removeprefix(_REFUSAL_MARKER).strip()
        return ModuleNotes(
            module_title=module.title,
            body="",
            cited_chunk_ids=[],
            chunks=chunks,
            refused=True,
            refusal_reason=reason.split("\n", 1)[0].lstrip(": ").strip(),
        )

    retrieved_ids = {c.id for c in chunks}
    cited = [int(m) for m in _CITATION.findall(body)]
    # A citation pointing outside the retrieved set is a hard bug, not a scoring
    # question — surface it rather than letting the eval layer find it later.
    invalid = sorted(set(cited) - retrieved_ids)
    if invalid:
        raise RuntimeError(f"Notes cited chunks that were never retrieved: {invalid}")

    quiz = None
    if with_quiz:
        quiz = generate_quiz(module, chunks, passages=passages)

    return ModuleNotes(
        module_title=module.title,
        body=body,
        cited_chunk_ids=sorted(set(cited)),
        chunks=chunks,
        quiz=quiz,
    )


def generate_quiz(
    module: Module,
    chunks: list[Chunk],
    *,
    passages: str | None = None,
    n: int = 3,
) -> Quiz:
    """Sync counterpart of `agenerate_quiz`, used by the CLI and eval.

    Same reasoning: plain text first so the cached passages are reused, with
    structured output as the fallback when the layout does not parse.
    """
    block = passages or f"Source passages:\n\n{_format_passages(chunks)}"
    prompt = f"Module: {module.title}\n\n{_QUIZ_TASK.format(n=n)}"

    raw = llm.complete(
        model=config.GENERATION_MODEL,
        system=_GROUNDING_SYSTEM,
        cached_prefix=block,
        prompt=prompt,
        max_tokens=config.MAX_TOKENS_QUIZ,
    )
    quiz = parse_quiz(raw)

    if quiz is None:
        quiz = llm.parse(
            model=config.GENERATION_MODEL,
            system=_GROUNDING_SYSTEM,
            cached_prefix=block,
            prompt=prompt,
            max_tokens=config.MAX_TOKENS_QUIZ,
            schema=Quiz,
        )

    quiz.questions = [q for q in quiz.questions if 0 <= q.answer_index < len(q.options)]
    return quiz


async def astream_module_notes(
    module: Module,
    *,
    namespace: str,
    cfg: config.RetrievalConfig | None = None,
    with_quiz: bool = False,
    style: StyleProfile | None = None,
) -> AsyncIterator[dict]:
    """Same work as `generate_module_notes`, emitted as it is written.

    Yields `token` events while the notes generate, then one terminal `module`
    event carrying the complete `ModuleNotes`. A client renders the prose as it
    arrives and swaps in the final object for citations and quiz.
    """
    cfg = cfg or config.EMBEDDING

    # Retrieval is CPU-bound torch work behind a lock, so it goes to a thread
    # rather than blocking the event loop the other modules are streaming on.
    chunks = await asyncio.to_thread(
        retrieval.retrieve_multi,
        [module.query, *module.learning_goals],
        namespace=namespace,
        cfg=cfg,
    )

    refusal = _refusal_for(module, chunks)
    if refusal:
        yield {"type": "module", "notes": refusal.model_dump()}
        return

    goals = "\n".join(f"- {g}" for g in module.learning_goals)
    passages = f"Source passages:\n\n{_format_passages(chunks)}"
    style_instruction = f"\n\n{style.as_instruction()}" if style else ""

    body = ""
    holding = True
    suppressed = False

    async for delta in llm.astream_complete(
        model=config.GENERATION_MODEL,
        system=_GROUNDING_SYSTEM,
        cached_prefix=passages,
        prompt=(
            f"Module: {module.title}\n\n"
            f"The reader should come away able to:\n{goals}\n\n"
            f"{_NOTES_TASK}{style_instruction}"
        ),
        max_tokens=config.MAX_TOKENS_NOTES,
    ):
        body += delta
        if holding:
            # A refusal announces itself only in the first word. Hold the
            # opening back until there is enough text to tell; emitting first
            # and retracting would flash discarded prose at the reader.
            if len(body) < len(_REFUSAL_MARKER):
                continue
            holding = False
            suppressed = body.startswith(_REFUSAL_MARKER)
            if not suppressed:
                yield {"type": "token", "text": body}
        elif not suppressed:
            yield {"type": "token", "text": delta}

    if body.strip().startswith(_REFUSAL_MARKER):
        reason = body.strip().removeprefix(_REFUSAL_MARKER).strip()
        yield {
            "type": "module",
            "notes": ModuleNotes(
                module_title=module.title,
                body="",
                cited_chunk_ids=[],
                chunks=chunks,
                refused=True,
                refusal_reason=reason.split("\n", 1)[0].lstrip(": ").strip(),
            ).model_dump(),
        }
        return

    retrieved_ids = {c.id for c in chunks}
    cited = [int(m) for m in _CITATION.findall(body)]
    invalid = sorted(set(cited) - retrieved_ids)
    if invalid:
        raise RuntimeError(f"Notes cited chunks that were never retrieved: {invalid}")

    quiz = None
    if with_quiz:
        quiz = await agenerate_quiz(module, chunks, passages=passages)

    yield {
        "type": "module",
        "notes": ModuleNotes(
            module_title=module.title,
            body=body,
            cited_chunk_ids=sorted(set(cited)),
            chunks=chunks,
            quiz=quiz,
        ).model_dump(),
    }


async def agenerate_quiz(
    module: Module, chunks: list[Chunk], *, passages: str | None = None, n: int = 3
) -> Quiz:
    """Questions from the same passages the notes were written from.

    Tries the plain-text path first, which reuses the cached passages; falls
    back to structured output if the layout comes back unparseable, so a format
    slip costs money rather than the feature.
    """
    block = passages or f"Source passages:\n\n{_format_passages(chunks)}"
    prompt = f"Module: {module.title}\n\n{_QUIZ_TASK.format(n=n)}"

    raw = await llm.astream_text(
        model=config.GENERATION_MODEL,
        system=_GROUNDING_SYSTEM,
        cached_prefix=block,
        prompt=prompt,
        max_tokens=config.MAX_TOKENS_QUIZ,
    )
    quiz = parse_quiz(raw)

    if quiz is None:
        quiz = await llm.aparse(
            model=config.GENERATION_MODEL,
            system=_GROUNDING_SYSTEM,
            cached_prefix=block,
            prompt=prompt,
            max_tokens=config.MAX_TOKENS_QUIZ,
            schema=Quiz,
        )

    quiz.questions = [q for q in quiz.questions if 0 <= q.answer_index < len(q.options)]
    return quiz


async def arun_course_events(
    goal: str,
    *,
    limit: int = 10,
    cfg: config.RetrievalConfig | None = None,
    skip_ingest: bool = False,
    syllabus: Syllabus | None = None,
    with_quiz: bool = False,
    namespace: str | None = None,
    style: StyleProfile | None = None,
    cancel_event: asyncio.Event | None = None,
    only_indices: set[int] | None = None,
) -> AsyncIterator[dict]:
    """Plan, then stream every module concurrently as coroutines.

    Modules run on one event loop rather than in a thread pool. Streaming is
    I/O-bound but its SSE parsing is Python work, so threads contended on the
    GIL and staggered each other's first token by seconds; coroutines do not.

    `cancel_event` stops workers when set (explicit Stop). Leaving the SSE
    stream does not set it — background jobs keep writing.

    `only_indices` regenerates a subset (resume of a partial course).
    """
    cfg = cfg or config.EMBEDDING

    if syllabus is None:
        yield {"type": "planning"}
        syllabus = await asyncio.to_thread(plan_syllabus, goal)

    if namespace:
        skip_ingest = True
    namespace = namespace or syllabus.topic_slug

    yield {
        "type": "syllabus",
        "title": syllabus.title,
        "summary": syllabus.summary,
        "namespace": namespace,
        "modules": [m.title for m in syllabus.modules],
        "syllabus": syllabus.model_dump(),
    }

    if not skip_ingest:
        yield {"type": "ingesting", "namespace": namespace}
        summary = await asyncio.to_thread(
            ingest.ingest_topic,
            slug=syllabus.topic_slug,
            query=[
                syllabus.topic_slug.replace("-", " "),
                *(m.query for m in syllabus.modules),
            ],
            namespace=namespace,
            limit=limit,
            cfg=cfg,
        )
        yield {
            "type": "ingested",
            "cached": summary.get("cached", False),
            "chunks": summary.get("chunks", 0),
        }

    await asyncio.to_thread(embedding.warm, cfg)

    indices = (
        only_indices
        if only_indices is not None
        else set(range(len(syllabus.modules)))
    )
    work = [(i, m) for i, m in enumerate(syllabus.modules) if i in indices]
    if not work:
        entries, cost = llm.usage_report()
        yield {
            "type": "done",
            "estimated_cost_usd": round(cost, 4),
            "usage": [e.model_dump() for e in entries],
        }
        return

    for index, module in work:
        yield {"type": "module_start", "index": index, "title": module.title}

    events: asyncio.Queue = asyncio.Queue()
    limiter = asyncio.Semaphore(config.MAX_PARALLEL_MODULES)

    async def worker(index: int, module: Module) -> None:
        try:
            async with limiter:
                async for event in astream_module_notes(
                    module,
                    namespace=namespace,
                    cfg=cfg,
                    with_quiz=with_quiz,
                    style=style,
                ):
                    await events.put({**event, "index": index})
        except Exception as exc:  # noqa: BLE001
            # One failed module must not lose the others already written.
            await events.put({"type": "module_error", "index": index, "error": str(exc)})
        finally:
            await events.put({"type": "_worker_done"})

    tasks = [asyncio.create_task(worker(i, m)) for i, m in work]
    remaining = len(tasks)
    cancelled = False
    try:
        while remaining:
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                break
            try:
                event = await asyncio.wait_for(events.get(), timeout=0.4)
            except TimeoutError:
                continue
            if event["type"] == "_worker_done":
                remaining -= 1
                continue
            yield event
    finally:
        if cancelled:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        else:
            await asyncio.gather(*tasks, return_exceptions=True)

    if cancelled:
        yield {"type": "cancelled"}
        return

    entries, cost = llm.usage_report()
    yield {
        "type": "done",
        "estimated_cost_usd": round(cost, 4),
        "usage": [e.model_dump() for e in entries],
    }


def run_course(
    goal: str,
    *,
    limit: int = 10,
    cfg: config.RetrievalConfig | None = None,
    skip_ingest: bool = False,
    syllabus: Syllabus | None = None,
    with_quiz: bool = False,
    namespace: str | None = None,
    style: StyleProfile | None = None,
) -> tuple[Syllabus, list[ModuleNotes]]:
    """Plan, ensure the corpus exists, then run every module concurrently.

    Passing `syllabus` skips planning. Evaluation runs must do this: the planner
    emits a different breakdown each time, so re-planning between two measured
    runs means they cover different work and any before/after difference
    conflates the change under test with planner variance.
    """
    cfg = cfg or config.EMBEDDING

    syllabus = syllabus or plan_syllabus(goal)

    # An explicit namespace means "build this course only from what is already
    # in here" — the uploaded-material path. Fetching from open sources would
    # defeat the point, so it is skipped.
    if namespace:
        skip_ingest = True
    namespace = namespace or syllabus.topic_slug

    if not skip_ingest:
        summary = ingest.ingest_topic(
            slug=syllabus.topic_slug,
            query=[
                syllabus.topic_slug.replace("-", " "),
                *(m.query for m in syllabus.modules),
            ],
            namespace=namespace,
            limit=limit,
            cfg=cfg,
        )
        if summary.get("cached"):
            print(f"Corpus cache hit: {summary['chunks']} chunks already indexed.")

    # Load the local models here, on one thread, before the pool starts.
    embedding.warm(cfg)

    # Modules are independent once the syllabus exists, so they run in parallel.
    # This is the single biggest latency lever in the project.
    with ThreadPoolExecutor(max_workers=config.MAX_PARALLEL_MODULES) as pool:
        notes = list(
            pool.map(
                lambda m: generate_module_notes(
                    m, namespace=namespace, cfg=cfg, with_quiz=with_quiz, style=style
                ),
                syllabus.modules,
            )
        )

    return syllabus, notes
