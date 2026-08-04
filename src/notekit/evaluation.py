"""Side lane: does the generated text actually follow from its sources?

Faithfulness is measured the way Ragas measures it — decompose the notes into
atomic claims, then check each claim for entailment against the retrieved
passages — but implemented directly here rather than through the library. Two
reasons: Ragas routes through LangChain and defaults to OpenAI, which would add
a second provider to a project that deliberately has one; and an eval whose
scoring is a black box undercuts the point of the project. Every judgement here
is inspectable, and `--explain` prints the reasoning per claim.

Nothing in this module is on the user-facing critical path.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel, Field

from . import config, llm
from .models import Chunk, Module, ModuleNotes

_CLAIMS_SYSTEM = """You decompose study notes into atomic factual claims.

An atomic claim is a single assertion that can be checked on its own. Split \
compound sentences. Resolve pronouns to what they refer to, so each claim \
stands alone without context.

Ignore citation markers like [c123]. Ignore sentences that make no factual \
assertion, such as transitions or restatements of the module title."""

_VERDICT_SYSTEM = """You check whether claims are supported by source passages.

For each numbered claim, decide whether the passages entail it. Judge only \
what the passages actually say: a claim that is true in general but absent \
from the passages is NOT supported. A claim that paraphrases the passages \
faithfully IS supported.

Give a one-sentence reason for every verdict."""

_COVERAGE_SYSTEM = """You check whether study notes address stated learning goals.

For each numbered goal, decide whether the notes give a reader enough to meet \
it. Partial treatment that leaves the goal substantially unmet counts as not \
addressed."""


class _Claims(BaseModel):
    claims: list[str] = Field(description="Atomic factual claims, in order")


class _Verdict(BaseModel):
    claim_index: int = Field(description="1-based index of the claim")
    supported: bool
    reason: str


class _Verdicts(BaseModel):
    verdicts: list[_Verdict]


class _GoalVerdict(BaseModel):
    goal_index: int = Field(description="1-based index of the learning goal")
    addressed: bool
    reason: str


class _GoalVerdicts(BaseModel):
    verdicts: list[_GoalVerdict]


class ClaimCheck(BaseModel):
    claim: str
    supported: bool
    reason: str


class ModuleEval(BaseModel):
    module_title: str
    refused: bool = False

    claims: list[ClaimCheck] = []
    coverage: list[ClaimCheck] = []

    @property
    def faithfulness(self) -> float | None:
        """Share of claims entailed by the retrieved passages."""
        if not self.claims:
            return None
        return sum(c.supported for c in self.claims) / len(self.claims)

    @property
    def coverage_score(self) -> float | None:
        if not self.coverage:
            return None
        return sum(c.supported for c in self.coverage) / len(self.coverage)

    @property
    def unsupported(self) -> list[ClaimCheck]:
        return [c for c in self.claims if not c.supported]


def _passages(chunks: list[Chunk]) -> str:
    return "\n\n".join(f"[{c.citation_key}] {c.text}" for c in chunks)


def evaluate_module(notes: ModuleNotes, module: Module) -> ModuleEval:
    """Score one module's notes for faithfulness and coverage."""
    if notes.refused:
        # A refusal has no claims to check. Whether refusing was *correct* is a
        # separate question, answered by the calibration set.
        return ModuleEval(module_title=notes.module_title, refused=True)

    extracted = llm.parse(
        model=config.JUDGE_MODEL,
        system=_CLAIMS_SYSTEM,
        prompt=f"Study notes:\n\n{notes.body}",
        max_tokens=4000,
        schema=_Claims,
    )
    if not extracted.claims:
        return ModuleEval(module_title=notes.module_title)

    numbered = "\n".join(f"{i}. {c}" for i, c in enumerate(extracted.claims, 1))
    verdicts = llm.parse(
        model=config.JUDGE_MODEL,
        system=_VERDICT_SYSTEM,
        prompt=(
            f"Source passages:\n\n{_passages(notes.chunks)}\n\n"
            f"Claims to check:\n{numbered}"
        ),
        max_tokens=8000,
        schema=_Verdicts,
    )

    by_index = {v.claim_index: v for v in verdicts.verdicts}
    claims = [
        ClaimCheck(
            claim=claim,
            # An unjudged claim counts against faithfulness rather than being
            # dropped, so a truncated judge response cannot inflate the score.
            supported=by_index[i].supported if i in by_index else False,
            reason=by_index[i].reason if i in by_index else "No verdict returned.",
        )
        for i, claim in enumerate(extracted.claims, 1)
    ]

    goals = "\n".join(f"{i}. {g}" for i, g in enumerate(module.learning_goals, 1))
    goal_verdicts = llm.parse(
        model=config.JUDGE_MODEL,
        system=_COVERAGE_SYSTEM,
        prompt=f"Study notes:\n\n{notes.body}\n\nLearning goals:\n{goals}",
        max_tokens=2000,
        schema=_GoalVerdicts,
    )
    by_goal = {v.goal_index: v for v in goal_verdicts.verdicts}
    coverage = [
        ClaimCheck(
            claim=goal,
            supported=by_goal[i].addressed if i in by_goal else False,
            reason=by_goal[i].reason if i in by_goal else "No verdict returned.",
        )
        for i, goal in enumerate(module.learning_goals, 1)
    ]

    return ModuleEval(module_title=notes.module_title, claims=claims, coverage=coverage)


def evaluate_course(
    notes: list[ModuleNotes], modules: list[Module]
) -> list[ModuleEval]:
    """Score every module. Runs concurrently — this lane blocks nobody."""
    with ThreadPoolExecutor(max_workers=config.MAX_PARALLEL_MODULES) as pool:
        return list(pool.map(evaluate_module, notes, modules))


def aggregate(results: list[ModuleEval]) -> dict:
    scored = [r for r in results if r.faithfulness is not None]
    covered = [r for r in results if r.coverage_score is not None]
    total_claims = sum(len(r.claims) for r in scored)
    supported = sum(sum(c.supported for c in r.claims) for r in scored)

    return {
        "modules": len(results),
        "refused": sum(r.refused for r in results),
        "claims": total_claims,
        "supported": supported,
        # Claim-weighted, not module-weighted: a module with 30 claims should
        # count for more than one with 3.
        "faithfulness": supported / total_claims if total_claims else None,
        "coverage": (
            sum(r.coverage_score for r in covered) / len(covered) if covered else None
        ),
    }
