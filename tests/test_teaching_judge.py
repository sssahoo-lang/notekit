"""The third judge: did the notes teach the goals, not merely address them.

Faithfulness says nothing was made up. Coverage says each goal was addressed.
A section can satisfy both by reporting, faithfully and on every goal, that the
sources do not cover it, and teach nothing. That course happened. The teaching
judge scores each goal on a 0-3 rubric so the number that moves when a course
gets better is separate from the numbers that move when it gets safer."""

from notekit import evaluation
from notekit.models import Module, ModuleNotes


def notes(body="Descent follows the negative gradient [c1].", refused=False):
    return ModuleNotes(module_title="GD", body=body, cited_chunk_ids=[1], chunks=[], refused=refused)


def module(goals=("Define gradient descent", "Explain the step size")):
    return Module(title="GD", query="gd", learning_goals=list(goals))


def fake_parse(scores=None, drop=()):
    """Answer each judge by schema. `scores` maps goal_index to a teaching score."""
    def parse(**kw):
        name = kw["schema"].__name__
        if name == "_Claims":
            return kw["schema"](claims=["a claim"])
        if name == "_Verdicts":
            return kw["schema"](verdicts=[{"claim_index": 1, "supported": True, "reason": "r"}])
        if name == "_GoalVerdicts":
            return kw["schema"](verdicts=[{"goal_index": 1, "addressed": True, "reason": "r"},
                                          {"goal_index": 2, "addressed": True, "reason": "r"}])
        if name == "_TeachingVerdicts":
            return kw["schema"](verdicts=[
                {"goal_index": i, "score": s, "reason": "r"}
                for i, s in (scores or {1: 3, 2: 1}).items() if i not in drop
            ])
        raise AssertionError(name)
    return parse


def test_the_score_is_the_rubric_mean_as_a_fraction_of_three(monkeypatch):
    monkeypatch.setattr(evaluation.llm, "parse", fake_parse({1: 3, 2: 1}))
    r = evaluation.evaluate_module(notes(), module())
    assert r.teaching_score == (3 + 1) / 6


def test_a_goal_the_judge_skipped_scores_zero_not_missing(monkeypatch):
    # Same reasoning as an unjudged claim counting as unsupported: a short
    # response must not read as a good one.
    monkeypatch.setattr(evaluation.llm, "parse", fake_parse({1: 3, 2: 3}, drop=(2,)))
    r = evaluation.evaluate_module(notes(), module())
    assert [t.score for t in r.teaching] == [3, 0]
    assert "No verdict" in r.teaching[1].reason


def test_teaching_is_distinct_from_coverage(monkeypatch):
    # Every goal addressed, nothing taught: the case that motivated this.
    monkeypatch.setattr(evaluation.llm, "parse", fake_parse({1: 0, 2: 0}))
    r = evaluation.evaluate_module(notes("The passages do not define this [c1]."), module())
    assert r.coverage_score == 1.0
    assert r.teaching_score == 0.0


def test_the_level_reaches_the_judge(monkeypatch):
    seen = {}
    def parse(**kw):
        if kw["schema"].__name__ == "_TeachingVerdicts":
            seen["prompt"] = kw["prompt"]
        return fake_parse()(**kw)
    monkeypatch.setattr(evaluation.llm, "parse", parse)
    evaluation.evaluate_module(notes(), module(), level="beginner")
    assert "Reader level: beginner" in seen["prompt"]


def test_a_refusal_has_no_teaching_score(monkeypatch):
    monkeypatch.setattr(evaluation.llm, "parse", lambda **kw: (_ for _ in ()).throw(AssertionError("no judge call")))
    r = evaluation.evaluate_module(notes(refused=True), module())
    assert r.teaching == [] and r.teaching_score is None


def test_aggregate_reports_teaching_beside_the_others(monkeypatch):
    monkeypatch.setattr(evaluation.llm, "parse", fake_parse({1: 3, 2: 3}))
    results = [evaluation.evaluate_module(notes(), module()), evaluation.evaluate_module(notes(refused=True), module())]
    summary = evaluation.aggregate(results)
    assert summary["teaching"] == 1.0
    assert summary["refused"] == 1
