"""The course loop as a state graph, with one real decision in it.

A straight line of plan → gather → write does not need a graph; a for-loop
expresses it better and this project ran that way for a long time. What earns
the graph is the failure we actually hit: build a course on a corpus that turns
out to be thin, and modules refuse — correctly, but leaving the reader with a
mostly empty course and no recourse.

So the graph branches. After writing, it counts refusals: if too many sections
had nothing to work from and there is an attempt left, it routes to a node that
widens the corpus using the refused sections' own queries, then rewrites only
those sections. Otherwise it finishes. That is a decision made from the state of
the run, which is the thing a graph is for.

The streaming API path keeps its own orchestration — it has to emit tokens as
they arrive and cancel mid-flight, which this does not model. This runs the
synchronous path used by the CLI and evaluation.
"""

from __future__ import annotations

from typing import Annotated, TypedDict

from langgraph.graph import END, StateGraph

from . import config, embedding, ingest
from .models import ModuleNotes, Syllabus
from .pipeline import generate_module_notes, plan_syllabus

# How much of a course has to be unwritable before widening the corpus is worth
# the fetch. Below this, a refusal is probably honest rather than a corpus gap.
REFUSAL_FRACTION_TO_RETRY = 0.4
MAX_BROADEN_ATTEMPTS = 1


def _merge(existing: dict[int, ModuleNotes], incoming: dict[int, ModuleNotes]):
    return {**existing, **incoming}


class CourseState(TypedDict, total=False):
    goal: str
    namespace: str | None
    limit: int
    with_quiz: bool
    style: object | None
    cfg: object | None
    skip_ingest: bool

    syllabus: Syllabus
    resolved_namespace: str
    notes: Annotated[dict[int, ModuleNotes], _merge]
    attempts: int
    broadened: bool


def _plan(state: CourseState) -> dict:
    syllabus = state.get("syllabus") or plan_syllabus(state["goal"])
    namespace = state.get("namespace") or syllabus.topic_slug
    return {"syllabus": syllabus, "resolved_namespace": namespace, "attempts": 0}


def _gather(state: CourseState) -> dict:
    # An explicit namespace means "use only what is already here".
    if state.get("skip_ingest") or state.get("namespace"):
        return {}
    syllabus = state["syllabus"]
    ingest.ingest_topic(
        slug=syllabus.topic_slug,
        query=[
            syllabus.topic_slug.replace("-", " "),
            *(m.query for m in syllabus.modules),
        ],
        namespace=state["resolved_namespace"],
        limit=state.get("limit", 10),
        cfg=state.get("cfg") or config.EMBEDDING,
    )
    return {}


def _write(state: CourseState) -> dict:
    cfg = state.get("cfg") or config.EMBEDDING
    embedding.warm(cfg)

    done = state.get("notes", {})
    # On a retry only the sections that refused are rewritten; the rest are
    # already paid for and good.
    todo = [
        m
        for i, m in enumerate(state["syllabus"].modules)
        if i not in done or done[i].refused
    ]

    written: dict[int, ModuleNotes] = {}
    for index, module in enumerate(state["syllabus"].modules):
        if module not in todo:
            continue
        written[index] = generate_module_notes(
            module,
            namespace=state["resolved_namespace"],
            cfg=cfg,
            with_quiz=state.get("with_quiz", False),
            style=state.get("style"),
        )
    return {"notes": written, "attempts": state.get("attempts", 0) + 1}


def _broaden(state: CourseState) -> dict:
    """Widen the corpus using the queries of the sections that refused."""
    refused = [
        state["syllabus"].modules[i]
        for i, n in state.get("notes", {}).items()
        if n.refused
    ]
    queries = [q for m in refused for q in (m.query, *m.learning_goals)]
    ingest.ingest_topic(
        slug=state["syllabus"].topic_slug,
        query=queries or [state["syllabus"].topic_slug.replace("-", " ")],
        namespace=state["resolved_namespace"],
        limit=max(4, state.get("limit", 10)),
        cfg=state.get("cfg") or config.EMBEDDING,
        force=True,
    )
    return {"broadened": True}


def _should_broaden(state: CourseState) -> str:
    """The graph's one real decision."""
    notes = state.get("notes", {})
    if not notes or state.get("attempts", 0) > MAX_BROADEN_ATTEMPTS:
        return "finish"
    # An explicit namespace is the reader's own material — fetching more from
    # the open web would silently break the promise that it used only their files.
    if state.get("namespace"):
        return "finish"

    refused = sum(1 for n in notes.values() if n.refused)
    if refused and refused / len(notes) >= REFUSAL_FRACTION_TO_RETRY:
        return "broaden"
    return "finish"


def build_graph():
    graph = StateGraph(CourseState)
    graph.add_node("plan", _plan)
    graph.add_node("gather", _gather)
    graph.add_node("write", _write)
    graph.add_node("broaden", _broaden)

    graph.set_entry_point("plan")
    graph.add_edge("plan", "gather")
    graph.add_edge("gather", "write")
    graph.add_conditional_edges(
        "write", _should_broaden, {"broaden": "broaden", "finish": END}
    )
    graph.add_edge("broaden", "write")
    return graph.compile()


_compiled = None


def run(**state) -> tuple[Syllabus, list[ModuleNotes]]:
    """Run a course through the graph. Same return shape as `run_course`."""
    global _compiled
    if _compiled is None:
        _compiled = build_graph()

    final = _compiled.invoke(state)
    notes = final.get("notes", {})
    return final["syllabus"], [notes[i] for i in sorted(notes)]
