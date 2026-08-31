"""Per-course form choices.

The load-bearing property is the first test: a course requested without
preferences has to generate exactly as it did before this module existed. Every
faithfulness figure in the README describes that prompt, so a default request
that quietly picks up extra instructions would invalidate all of them.

The rest cover the grounding contract. A preference may change how something is
written and must never license writing something the passages do not support,
which is why asking for examples or formulae renders as guidance to surface
what the passages hold rather than to produce examples on demand."""

import pytest

from notekit.preferences import NotePreferences


def test_no_choices_render_to_nothing():
    # Appending "" leaves the default prompt byte-identical.
    prefs = NotePreferences()
    assert prefs.is_empty()
    assert prefs.as_instruction() == ""


def test_any_single_choice_makes_it_non_empty():
    assert not NotePreferences(vocabulary="plain").is_empty()
    assert NotePreferences(vocabulary="plain").as_instruction() != ""


def test_false_is_a_choice_not_an_absence():
    # `examples=False` means "leave them out", which is not the same as not
    # having asked. A falsiness check rather than an `is not None` check would
    # collapse the two and silently drop the instruction.
    prefs = NotePreferences(examples=False, formulas=False, analogies=False)
    assert not prefs.is_empty()
    text = prefs.as_instruction()
    assert "not expected" in text
    assert "Analogies: avoid them" in text


@pytest.mark.parametrize(
    "prefs",
    [
        NotePreferences(examples=True),
        NotePreferences(formulas=True),
        NotePreferences(analogies=True),
    ],
)
def test_content_shaped_requests_never_license_invention(prefs):
    # These are the three preferences that could be read as "produce more of
    # this", which would collide with the grounding rule.
    text = prefs.as_instruction().lower()
    assert "never invent" in text or "do not reconstruct" in text


def test_the_preamble_states_the_grounding_precedence():
    text = NotePreferences(depth="thorough").as_instruction()
    assert "form only" in text
    assert "leave it unmet" in text


def test_depth_and_vocabulary_each_render_distinctly():
    brief = NotePreferences(depth="brief").as_instruction()
    thorough = NotePreferences(depth="thorough").as_instruction()
    assert brief != thorough
    plain = NotePreferences(vocabulary="plain").as_instruction()
    technical = NotePreferences(vocabulary="technical").as_instruction()
    assert plain != technical


def test_diagram_preference_keeps_the_invention_bar():
    prefer = NotePreferences(diagrams="prefer").as_instruction()
    assert "unchanged" in prefer
    assert "none" in NotePreferences(diagrams="avoid").as_instruction().lower()


def test_it_round_trips_through_storage():
    # Preferences are persisted as JSON so a resumed course writes its
    # remaining sections the same way as the first ones.
    prefs = NotePreferences(level="beginner", vocabulary="plain", examples=True)
    stored = prefs.model_dump(exclude_none=True)
    assert stored == {"level": "beginner", "vocabulary": "plain", "examples": True}
    assert NotePreferences(**stored).as_instruction() == prefs.as_instruction()


class TestTheDefaultRequestIsUnchanged:
    """The planner prompt with no stated level has to be the one the README's
    numbers were measured against, character for character. This is easy to
    break by rewording the shared part of the sentence while adding the
    conditional part."""

    HISTORICAL = (
        "Learning goal: gradient descent\n\n"
        "Match the inferred learner level, write retrieval-ready academic "
        "queries for each module, and keep learning goals observable."
    )

    def prompt_for(self, monkeypatch, **kwargs) -> str:
        from notekit import pipeline

        seen: dict[str, str] = {}

        def fake_parse(**call):
            seen["prompt"] = call["prompt"]
            raise RuntimeError("stop after capturing the prompt")

        monkeypatch.setattr(pipeline.llm, "parse", fake_parse)
        with pytest.raises(RuntimeError):
            pipeline.plan_syllabus("gradient descent", **kwargs)
        return seen["prompt"]

    def test_no_level_reproduces_the_historical_prompt(self, monkeypatch):
        assert self.prompt_for(monkeypatch) == self.HISTORICAL

    def test_a_stated_level_replaces_the_inference(self, monkeypatch):
        prompt = self.prompt_for(monkeypatch, level="beginner")
        assert "The reader states their level: beginner" in prompt
        assert "inferred" not in prompt
        # The rest of the instruction survives the substitution.
        assert "retrieval-ready academic queries" in prompt
