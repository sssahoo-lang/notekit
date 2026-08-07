"""normalize() is the one place a display name becomes a storage key.
Before this existed, "Ria Butt" and "ria butt" were different users with
different histories — every case here is a pair that must collapse."""

import pytest

from notekit.identity import ANONYMOUS, normalize


@pytest.mark.parametrize(
    "raw",
    ["Ria Butt", "ria butt", "Ria  Butt", "Ria.Butt", "ria_butt", "  Ria Butt  "],
)
def test_variants_collapse_to_the_same_key(raw):
    assert normalize(raw) == "ria-butt"


@pytest.mark.parametrize("raw", [None, "", "   ", "..."])
def test_empty_or_meaningless_input_is_anonymous(raw):
    assert normalize(raw) == ANONYMOUS


def test_disallowed_characters_are_dropped_not_substituted():
    # An emoji or punctuation mark isn't a word boundary, so it shouldn't
    # leave behind a stray hyphen the way a space or dot does.
    assert normalize("Ria🎉Butt") == "riabutt"
    assert normalize("Ria!Butt?") == "riabutt"


def test_runs_of_separators_collapse_to_one_hyphen():
    assert normalize("Ria...Butt") == "ria-butt"
    assert normalize("Ria   ...   Butt") == "ria-butt"


def test_leading_and_trailing_hyphens_are_stripped():
    assert normalize("-ria-butt-") == "ria-butt"
    assert normalize("...ria butt...") == "ria-butt"


def test_already_canonical_is_unchanged():
    assert normalize("ria-butt") == "ria-butt"


def test_digits_are_preserved():
    assert normalize("Reader 47") == "reader-47"
