"""Writing style as a per-user property, independent of any corpus.

A learner reads their own phrasing faster than generic explanatory prose. This
module learns how someone writes from a sample, then applies that to any course
they generate, whether it is built from their uploaded PDFs, from arXiv, or
from Wikipedia. Style and corpus are separate concerns.

The safety property: a `StyleProfile` describes *form only*. It never carries
subject matter, and the writing sample is not stored or sent at generation time.
Pasting a user's raw notes into the generation prompt as a style exemplar would
put content-shaped text beside the retrieved passages, and the model would
eventually assert things from it, the exact failure faithfulness exists to
catch. A structured description of form cannot do that.
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field

from . import config, db, llm

_SYSTEM = """You describe how a person writes, never what they write about.

You will be given a writing sample. Describe its FORM only: sentence rhythm, \
structure, register, person, vocabulary density, and habits of expression.

Critical constraints:
- Your description must contain no subject matter. Do not name topics, facts, \
domain terms, people, places, or examples from the sample.
- A reader of your description must learn nothing about what the sample was \
about. Describe the container, never the contents.
- summary and signature_habits are form-only. Reject any habit that smuggles \
content (e.g. "explains gradient descent with metaphors" is forbidden; \
"opens with a one-line definition before elaborating" is allowed).

For signature_habits, give two to five observable formatting and phrasing \
patterns, not the subject those habits were applied to."""


class StyleProfile(BaseModel):
    sentence_length: Literal["short", "medium", "long", "varied"]
    structure: Literal["prose", "bullets", "mixed"]
    formality: Literal["casual", "neutral", "formal"]
    person: Literal["first", "second", "third", "impersonal"] = Field(
        description="Grammatical person the writer addresses the reader in"
    )
    vocabulary: Literal["plain", "mixed", "technical"]
    uses_analogies: bool
    uses_worked_examples: bool
    uses_notation: bool = Field(description="Whether formulae or symbols appear")
    signature_habits: list[str] = Field(
        description="Two to five observable habits of form, no subject matter"
    )
    summary: str = Field(
        description="Two sentences on how this person writes. Form only, zero topics."
    )

    def as_instruction(self) -> str:
        """Render the profile as generation guidance."""
        traits = [
            f"- Sentences: {self.sentence_length}",
            f"- Structure: {self.structure}",
            f"- Register: {self.formality}, addressing the reader in the "
            f"{self.person} person",
            f"- Vocabulary: {self.vocabulary}",
            f"- Analogies: {'use them' if self.uses_analogies else 'avoid them'}",
            f"- Worked examples: "
            f"{'include them' if self.uses_worked_examples else 'not expected'}",
            f"- Notation: {'expected' if self.uses_notation else 'keep minimal'}",
        ]
        habits = "\n".join(f"- {h}" for h in self.signature_habits)
        return (
            "Write in the reader's own style, described below. This governs "
            "form only: it changes how you write, never what you may assert. "
            "Every grounding and citation rule still applies exactly as stated. "
            "If this profile asks for analogies or worked examples, use them "
            "only when the source passages themselves support them; never invent "
            "an analogy or example to match the style.\n\n"
            f"{self.summary}\n\n" + "\n".join(traits) + f"\n{habits}"
        )


def learn(sample: str) -> StyleProfile:
    """Extract a profile from a writing sample."""
    if len(sample.strip()) < 400:
        raise ValueError(
            "Writing sample is too short to characterise "
            f"({len(sample.strip())} chars; 400 minimum)."
        )
    # A long sample costs tokens without improving the description much.
    return llm.parse(
        model=config.PLANNER_MODEL,
        system=_SYSTEM,
        prompt=f"Writing sample:\n\n{sample[:12000]}",
        max_tokens=1500,
        schema=StyleProfile,
        purpose="learn-style",
    )


def save(user_id: str, profile: StyleProfile, sample_chars: int) -> None:
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO style_profiles (user_id, profile, sample_chars, updated_at)
            VALUES (%s, %s, %s, now())
            ON CONFLICT (user_id) DO UPDATE
                SET profile = EXCLUDED.profile,
                    sample_chars = EXCLUDED.sample_chars,
                    updated_at = now()
            """,
            (user_id, profile.model_dump_json(), sample_chars),
        )
        conn.commit()


def load(user_id: str) -> StyleProfile | None:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT profile FROM style_profiles WHERE user_id = %s", (user_id,)
        ).fetchone()
    if not row:
        return None
    raw = row["profile"]
    return StyleProfile.model_validate(
        json.loads(raw) if isinstance(raw, str) else raw
    )
