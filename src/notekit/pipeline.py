"""Hot lane: the only work a user waits on.

The functions below are written as discrete nodes over an explicit state dict so
they map onto a LangGraph `StateGraph` without restructuring: `plan_syllabus` is
the entry node, `generate_module_notes` is the per-module loop body, and
`run_course` is the executor. Milestone 1 runs them with a thread pool; swapping
in LangGraph is a wiring change once re-planning gives the graph something to
decide.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

from . import config, embedding, ingest, llm, retrieval
from .models import Chunk, Module, ModuleNotes, Quiz, Syllabus

_CITATION = re.compile(r"\[c(\d+)\]")

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

Each question needs exactly four options and one correct answer. Every question \
and its correct answer must be derivable from the passages alone — a reader who \
had only these passages should be able to answer. Wrong options must be \
plausible but clearly wrong given the passages, never true-but-unmentioned.

Cite the supporting passages as [c123] in each explanation."""


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


def generate_module_notes(
    module: Module,
    *,
    namespace: str,
    cfg: config.RetrievalConfig | None = None,
    with_quiz: bool = False,
) -> ModuleNotes:
    """Per-module loop body: retrieve, rerank, generate cited notes."""
    cfg = cfg or config.EMBEDDING
    # Retrieve for the module query and for each learning goal. Retrieving only
    # on the module query gave notes that were faithful but addressed barely
    # half the stated goals, because generation can only cover what it is shown.
    chunks = retrieval.retrieve_multi(
        [module.query, *module.learning_goals], namespace=namespace, cfg=cfg
    )

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

    goals = "\n".join(f"- {g}" for g in module.learning_goals)
    # Identical string in both calls: the quiz call can only read this from
    # cache if the notes call wrote exactly it.
    passages = f"Source passages:\n\n{_format_passages(chunks)}"

    body = llm.complete(
        model=config.GENERATION_MODEL,
        system=_GROUNDING_SYSTEM,
        cached_prefix=passages,
        prompt=(
            f"Module: {module.title}\n\n"
            f"The reader should come away able to:\n{goals}\n\n"
            f"{_NOTES_TASK}"
        ),
        max_tokens=config.MAX_TOKENS_NOTES,
    )

    if body.strip().startswith("INSUFFICIENT"):
        # Keep only the first line: the model sometimes ignores rule 3 and
        # appends partial notes anyway, which must not be reported as a reason.
        reason = body.strip().removeprefix("INSUFFICIENT").strip()
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
    """Questions answerable from the same passages the notes were written from.

    Reuses the notes call's cached passage block rather than retrieving again,
    so this costs a fraction of a fresh call.
    """
    quiz = llm.parse(
        model=config.GENERATION_MODEL,
        system=_GROUNDING_SYSTEM,
        cached_prefix=passages or f"Source passages:\n\n{_format_passages(chunks)}",
        prompt=f"Module: {module.title}\n\n{_QUIZ_TASK.format(n=n)}",
        max_tokens=config.MAX_TOKENS_QUIZ,
        schema=Quiz,
    )

    # A question whose answer index is out of range is unusable; drop it rather
    # than showing a quiz with no correct answer.
    quiz.questions = [
        q for q in quiz.questions if 0 <= q.answer_index < len(q.options)
    ]
    return quiz


def run_course(
    goal: str,
    *,
    limit: int = 10,
    cfg: config.RetrievalConfig | None = None,
    skip_ingest: bool = False,
    syllabus: Syllabus | None = None,
    with_quiz: bool = False,
    namespace: str | None = None,
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
                    m, namespace=namespace, cfg=cfg, with_quiz=with_quiz
                ),
                syllabus.modules,
            )
        )

    return syllabus, notes
