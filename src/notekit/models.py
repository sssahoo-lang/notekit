"""Domain types shared across the pipeline."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Module(BaseModel):
    title: str = Field(
        description=(
            "Short module title, three to eight words, sentence case. Name the "
            "concept, not the pedagogy (prefer 'Temporal-difference updates' "
            "over 'Understanding how updates work')."
        )
    )
    query: str = Field(
        description=(
            "Retrieval query written like an academic search string: field "
            "terms, definitions, and named methods. Never phrase it as a "
            "learner request ('teach me…', 'explain…'). Example: "
            "'Q-learning Bellman optimality equation action-value function'."
        )
    )
    learning_goals: list[str] = Field(
        description=(
            "Two to four observable outcomes after this module, matching the "
            "inferred learner level. Prefer verbs like define, derive, compare, "
            "apply, diagnose — not vague topics like 'know about X'."
        )
    )


class Syllabus(BaseModel):
    """Structured output of the planner call."""

    title: str = Field(
        default="",
        description=(
            "A short title for the course, three to six words, in sentence "
            "case. This is what the learner sees in their library, so it must "
            "read cleanly on its own — do not echo their phrasing or typos."
        )
    )
    topic_slug: str = Field(
        description=(
            "Canonical lowercase kebab-case slug for the overall subject, e.g. "
            "'reinforcement-learning'. Normalise abbreviations to their full form "
            "so that 'RL' and 'reinforcement learning' produce the same slug."
        )
    )
    summary: str = Field(
        description=(
            "One sentence describing what the course teaches and at what level, "
            "without marketing language."
        )
    )
    modules: list[Module] = Field(
        description="Three to five modules in pedagogical order, prerequisites first"
    )


class Chunk(BaseModel):
    """A retrieved passage, carrying everything a citation needs."""

    id: int
    text: str
    document_title: str
    document_url: str | None
    score: float = 0.0

    @property
    def citation_key(self) -> str:
        return f"c{self.id}"


class QuizQuestion(BaseModel):
    question: str
    options: list[str] = Field(description="Exactly four answer options")
    answer_index: int = Field(description="0-based index of the correct option")
    explanation: str = Field(
        description="Why the answer is correct, citing passages as [c123]"
    )


class Quiz(BaseModel):
    questions: list[QuizQuestion]


class ModuleNotes(BaseModel):
    module_title: str
    body: str
    cited_chunk_ids: list[int]
    chunks: list[Chunk]
    refused: bool = False
    refusal_reason: str | None = None
    quiz: Quiz | None = None


class Usage(BaseModel):
    """Token accounting, aggregated across a run."""

    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
