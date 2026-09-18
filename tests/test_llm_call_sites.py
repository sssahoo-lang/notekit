"""That the calls into llm.py match what llm.py accepts.

A course generated with practice questions failed every section with
`astream_text() got an unexpected keyword argument 'purpose'`. Tracing had
added `purpose` to astream_complete and to the call in agenerate_quiz, but not
to astream_text sitting between them. It went unnoticed for three weeks
because the streaming path is the one part of the pipeline the unit tests
deliberately leave to `notekit eval`, so nothing called it without a network.

Two tests. The first walks every `llm.*` call in the package and checks its
keywords against the real signature, which catches this whole class rather
than this one instance. The second exercises the quiz path that broke, with
the network faked at the boundary."""

import ast
import asyncio
import inspect
import pathlib

import pytest

from notekit import llm

SRC = pathlib.Path(__file__).resolve().parent.parent / "src" / "notekit"

QUIZ_TEXT = """Q: What does Q-learning estimate?
A) The optimal policy directly
B) The action-value function
C) The state transition model
D) The reward function
ANSWER: B
WHY: The passages define Q-learning as estimating action-values [c1]."""


def llm_signatures() -> dict[str, inspect.Signature]:
    out = {}
    for name, obj in vars(llm).items():
        if name.startswith("_") or not inspect.isfunction(obj):
            continue
        try:
            out[name] = inspect.signature(obj)
        except (TypeError, ValueError):  # pragma: no cover
            continue
    return out


def llm_calls():
    """Every `llm.something(...)` in the package, with its keyword names."""
    sigs = llm_signatures()
    for path in sorted(SRC.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "llm"
                and func.attr in sigs
            ):
                continue
            keywords = {kw.arg for kw in node.keywords if kw.arg}
            yield path.name, node.lineno, func.attr, keywords, sigs[func.attr]


def test_there_are_calls_to_check():
    # Guards the walk itself: an import rename would otherwise make this file
    # pass by finding nothing.
    assert len(list(llm_calls())) >= 5


def test_no_call_passes_an_argument_the_function_does_not_take():
    offenders = [
        f"{name}:{line} llm.{attr}() does not take {sorted(kw - set(sig.parameters))}"
        for name, line, attr, kw, sig in llm_calls()
        if kw - set(sig.parameters)
    ]
    assert not offenders, "\n".join(offenders)


def test_every_call_would_bind(monkeypatch):
    # Keywords alone miss a required argument nobody passed.
    for name, line, attr, keywords, sig in llm_calls():
        try:
            sig.bind_partial(**{k: None for k in keywords})
        except TypeError as exc:  # pragma: no cover
            pytest.fail(f"{name}:{line} llm.{attr}(): {exc}")


def test_the_quiz_path_reaches_the_model_with_its_trace_label(monkeypatch):
    """The exact call that failed, with the network faked one layer down.

    Driven with asyncio.run rather than pytest-asyncio: one coroutine does not
    justify a plugin, and the suite stays dependency-light.
    """
    from notekit import pipeline
    from notekit.models import Module

    seen: dict = {}

    # The layout parse_quiz actually accepts. An unparseable fake would send
    # agenerate_quiz down its structured-output fallback and out to the real
    # API, which is how the first version of this test came to spend money and
    # take a different amount of time on every run.
    async def fake_stream(**kwargs):
        seen.update(kwargs)
        for part in QUIZ_TEXT.splitlines(keepends=True):
            yield part

    async def no_network(**kwargs):
        raise AssertionError("the fallback path must not be reached here")

    monkeypatch.setattr(llm, "astream_complete", fake_stream)
    monkeypatch.setattr(llm, "aparse", no_network)

    asyncio.run(
        pipeline.agenerate_quiz(
            Module(
                title="TD learning", query="td", learning_goals=["Define TD error"]
            ),
            [],
            passages="Source passages:\n\n[c1] text",
            n=1,
        )
    )
    assert seen["purpose"] == "quiz", "the trace label must survive the wrapper"


def test_a_failing_quiz_does_not_discard_the_notes(monkeypatch):
    """The loss this bug actually caused.

    Every section of a course reported an error, not just a missing quiz. The
    prose had been generated and paid for, then thrown away, because the quiz
    call raised and the module worker turns any exception into a module_error.
    A quiz failure should cost the quiz.
    """
    from notekit import pipeline
    from notekit.models import Chunk, Module

    async def fake_stream(**kwargs):
        for part in ["Descent follows the negative gradient [c1]. ", "It converges [c1]."]:
            yield part

    async def exploding_quiz(*args, **kwargs):
        raise TypeError("astream_text() got an unexpected keyword argument 'purpose'")

    monkeypatch.setattr(pipeline.llm, "astream_complete", fake_stream)
    monkeypatch.setattr(pipeline, "agenerate_quiz", exploding_quiz)
    monkeypatch.setattr(
        pipeline.retrieval,
        "retrieve_multi",
        lambda *a, **k: [
            Chunk(
                id=1,
                citation_key="c1",
                text="The negative gradient is the direction of steepest decrease.",
                document_title="Optimization",
                document_url="https://example.org",
                score=9.0,
            )
        ],
    )

    async def collect():
        events = []
        async for event in pipeline.astream_module_notes(
            Module(title="Gradient descent", query="gd", learning_goals=["Define it"]),
            namespace="ns",
            with_quiz=True,
        ):
            events.append(event)
        return events

    events = asyncio.run(collect())
    modules = [e for e in events if e["type"] == "module"]

    assert modules, "the section must still be delivered"
    notes = modules[0]["notes"]
    assert notes["body"].strip(), "the written prose must survive a quiz failure"
    assert notes["quiz"] is None, "and the quiz is simply absent"
    assert not notes["refused"], "a quiz failure is not a refusal"


def test_a_section_that_runs_past_the_cap_is_retried_once_more_concisely(monkeypatch):
    """A first attempt that hits max_tokens is retracted and retried with a
    length instruction, rather than stored as a fragment or lost."""
    from notekit import pipeline
    from notekit.models import Chunk, Module

    prompts: list[str] = []

    async def stream(**kw):
        prompts.append(kw["prompt"])
        if len(prompts) == 1:
            yield "A long start that will be cut [c1]. "
            raise RuntimeError("Generation stopped early (max_tokens) after 8000 tokens; the text is incomplete.")
        yield "Short and complete [c1]."

    monkeypatch.setattr(pipeline.llm, "astream_complete", stream)
    monkeypatch.setattr(pipeline.retrieval, "retrieve_multi", lambda *a, **k: [
        Chunk(id=1, citation_key="c1", text="t", document_title="D", document_url=None, score=9.0)])

    async def collect():
        return [e async for e in pipeline.astream_module_notes(
            Module(title="M", query="q", learning_goals=["g"]), namespace="ns", with_quiz=False)]

    events = asyncio.run(collect())
    kinds = [e["type"] for e in events]
    assert "module_restart" in kinds, "the reader is told the draft is being retracted"
    assert kinds.index("module_restart") < kinds.index("module")
    assert events[-1]["notes"]["body"] == "Short and complete [c1]."
    assert len(prompts) == 2 and "1,500 words" in prompts[1] and "1,500 words" not in prompts[0]


def test_a_second_overrun_is_not_retried_again(monkeypatch):
    from notekit import pipeline
    from notekit.models import Chunk, Module

    async def stream(**kw):
        yield "x [c1]"
        raise RuntimeError("Generation stopped early (max_tokens) after 8000 tokens; the text is incomplete.")

    monkeypatch.setattr(pipeline.llm, "astream_complete", stream)
    monkeypatch.setattr(pipeline.retrieval, "retrieve_multi", lambda *a, **k: [
        Chunk(id=1, citation_key="c1", text="t", document_title="D", document_url=None, score=9.0)])

    async def collect():
        return [e async for e in pipeline.astream_module_notes(
            Module(title="M", query="q", learning_goals=["g"]), namespace="ns", with_quiz=False)]

    with pytest.raises(RuntimeError, match="max_tokens"):
        asyncio.run(collect())
