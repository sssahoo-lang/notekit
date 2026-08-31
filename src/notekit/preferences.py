"""What the reader asks for before a course is written.

Style (style.py) is learned from a writing sample and belongs to a person.
Preferences are chosen per course, because the same reader wants plain English
for a subject they are new to and dense notation for one they are not. Both end
up in the same place: guidance appended to the user turn, after the cached
prefix, so neither disturbs the prompt cache the notes and quiz calls share.

The safety property is style.py's, for style.py's reason. A preference
describes form, never subject matter, so it cannot smuggle content in beside
the retrieved passages.

Worked examples and formulae look like exceptions and are not. Asking for
either cannot conjure it: the passages either contain them or they do not, and
the rendered instruction says so explicitly. A reader who asks for examples and
silently receives invented ones is worse off than one who asks and gets none,
which is the same trade the refusal path already makes at the level of a whole
section.

Every field is optional, and a preference set with nothing chosen renders to
the empty string. That matters more than it looks: the default request has to
produce exactly the prompt it produced before this module existed, or every
measured number in the README describes something that no longer runs.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

Level = Literal["beginner", "intermediate", "advanced"]


class NotePreferences(BaseModel):
    """Per-course choices about the form of the notes."""

    level: Level | None = None
    vocabulary: Literal["plain", "mixed", "technical"] | None = None
    depth: Literal["brief", "standard", "thorough"] | None = None
    structure: Literal["prose", "bullets", "mixed"] | None = None
    examples: bool | None = None
    formulas: bool | None = None
    analogies: bool | None = None
    diagrams: Literal["auto", "prefer", "avoid"] | None = None

    def is_empty(self) -> bool:
        """True when the reader chose nothing, so generation is unchanged."""
        return not any(
            v is not None for v in self.model_dump(exclude_none=False).values()
        )

    def as_instruction(self) -> str:
        """Render the chosen preferences as generation guidance.

        Returns "" when nothing is set, so the caller can append
        unconditionally without changing the default prompt.
        """
        lines: list[str] = []

        if self.level:
            lines.append(
                f"- Pitch: write for a {self.level} reader. Assume what that "
                "reader plausibly knows and explain the rest."
            )
        if self.vocabulary == "plain":
            lines.append(
                "- Vocabulary: plain English. Where a technical term is "
                "unavoidable, define it from the passages on first use."
            )
        elif self.vocabulary == "technical":
            lines.append(
                "- Vocabulary: use the field's own terms as the passages use "
                "them, without softening them into everyday paraphrase."
            )
        elif self.vocabulary == "mixed":
            lines.append(
                "- Vocabulary: technical terms alongside plain restatements."
            )
        if self.depth == "brief":
            lines.append(
                "- Length: compact. A paragraph or two per learning goal."
            )
        elif self.depth == "thorough":
            lines.append(
                "- Length: expansive. Develop each learning goal over several "
                "paragraphs, as far as the passages support and no further."
            )
        elif self.depth == "standard":
            lines.append("- Length: a few paragraphs per learning goal.")
        if self.structure:
            lines.append(f"- Structure: {self.structure}.")
        if self.examples is True:
            lines.append(
                "- Worked examples: draw out the examples the passages "
                "contain and show them in full. If the passages contain none, "
                "write without them; never invent one to satisfy this."
            )
        elif self.examples is False:
            lines.append("- Worked examples: not expected. Keep to the ideas.")
        if self.formulas is True:
            lines.append(
                "- Formulae and notation: give the symbolic form wherever a "
                "passage states it, and define each symbol. Do not reconstruct "
                "or derive notation the passages do not show."
            )
        elif self.formulas is False:
            lines.append(
                "- Formulae and notation: keep minimal. Prefer prose."
            )
        if self.analogies is True:
            lines.append(
                "- Analogies: use one where a passage itself offers the "
                "comparison. Never invent an analogy to satisfy this."
            )
        elif self.analogies is False:
            lines.append("- Analogies: avoid them.")
        if self.diagrams == "prefer":
            lines.append(
                "- Diagrams: include one wherever the passages describe a "
                "process, cycle, hierarchy, or comparison clearly enough to "
                "draw. The bar on inventing nodes or edges is unchanged."
            )
        elif self.diagrams == "avoid":
            lines.append("- Diagrams: none. Explain in prose instead.")

        if not lines:
            return ""

        return (
            "The reader asked for the notes in the shape below. Where it "
            "conflicts with the general guidance above, this wins.\n\n"
            "It governs form only: it changes how you write, never what you "
            "may assert. Every grounding and citation rule still applies "
            "exactly as stated. Where a preference cannot be met from the "
            "passages, follow the passages and leave it unmet. Inventing "
            "content to satisfy a preference is the one thing it must never "
            "cause.\n\n" + "\n".join(lines)
        )
