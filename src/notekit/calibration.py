"""Choosing the refusal threshold from data rather than by guess.

`REFUSAL_SCORE_THRESHOLD` decides when the system says "your sources don't cover
this". It cannot be picked sensibly in the abstract: cross-encoder scores are
unbounded logits whose useful range depends on the reranker and the corpus. This
module measures the score distribution over questions known to be covered and
questions known to be absent, then reports the threshold that separates them
best.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from . import config, retrieval


class CalibrationSet(BaseModel):
    namespace: str
    covered: list[str]
    uncovered: list[str]

    @classmethod
    def load(cls, path: str | Path) -> CalibrationSet:
        return cls.model_validate_json(Path(path).read_text())


class Probe(BaseModel):
    query: str
    expected_covered: bool
    top_score: float | None


class CalibrationReport(BaseModel):
    probes: list[Probe]
    suggested_threshold: float | None
    accuracy: float | None
    current_threshold: float
    current_accuracy: float | None
    applied: bool = False
    applied_path: str | None = None

    @property
    def separated(self) -> bool:
        """True when no single threshold misclassifies anything."""
        return self.accuracy == 1.0


def _score(query: str, namespace: str, cfg: config.RetrievalConfig) -> float | None:
    chunks = retrieval.retrieve(query=query, namespace=namespace, cfg=cfg)
    return chunks[0].score if chunks else None


def _accuracy(probes: list[Probe], threshold: float) -> float:
    correct = 0
    for p in probes:
        predicted_covered = p.top_score is not None and p.top_score >= threshold
        correct += predicted_covered == p.expected_covered
    return correct / len(probes) if probes else 0.0


def calibrate(
    calset: CalibrationSet,
    cfg: config.RetrievalConfig | None = None,
    *,
    apply: bool = False,
) -> CalibrationReport:
    cfg = cfg or config.EMBEDDING
    current = config.refusal_score_threshold()

    probes = [
        Probe(query=q, expected_covered=True, top_score=_score(q, calset.namespace, cfg))
        for q in calset.covered
    ] + [
        Probe(query=q, expected_covered=False, top_score=_score(q, calset.namespace, cfg))
        for q in calset.uncovered
    ]

    scores = sorted({p.top_score for p in probes if p.top_score is not None})
    if not scores:
        return CalibrationReport(
            probes=probes,
            suggested_threshold=None,
            accuracy=None,
            current_threshold=current,
            current_accuracy=None,
        )

    # Sweep candidate thresholds at the midpoints between observed scores, so
    # the chosen value sits in the widest gap rather than on top of a datapoint.
    candidates = [scores[0] - 1.0] + [
        (a + b) / 2 for a, b in zip(scores, scores[1:], strict=False)
    ] + [scores[-1] + 1.0]
    best = max(candidates, key=lambda t: (_accuracy(probes, t), -abs(t)))

    applied = False
    applied_path: str | None = None
    if apply:
        config.set_refusal_score_threshold(best, persist=True)
        applied = True
        applied_path = str(config.REFUSAL_THRESHOLD_PATH)

    return CalibrationReport(
        probes=probes,
        suggested_threshold=best,
        accuracy=_accuracy(probes, best),
        current_threshold=current,
        current_accuracy=_accuracy(probes, current),
        applied=applied,
        applied_path=applied_path,
    )
