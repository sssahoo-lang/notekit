"""Domain types shared across the pipeline."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Module(BaseModel):
    title: str = Field(description="Short module title")
    query: str = Field(
        description="A focused retrieval query for this module's source material"
    )
    learning_goals: list[str] = Field(
        description="Two to four things the reader should be able to do after this module"
    )


class Syllabus(BaseModel):
    """Structured output of the planner call."""

    topic_slug: str = Field(
        description=(
            "Canonical lowercase kebab-case slug for the overall subject, e.g. "
            "'reinforcement-learning'. Normalise abbreviations to their full form "
            "so that 'RL' and 'reinforcement learning' produce the same slug."
        )
    )
    summary: str = Field(description="One sentence describing the course")
    modules: list[Module]


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
