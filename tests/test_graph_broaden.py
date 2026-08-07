"""_should_broaden is the graph's one real decision: after writing, does a
thin corpus deserve one retry with widened sources, or does high refusal mean
the request is honestly out of scope? Two invariants matter most: an
uploaded-material course must never widen to the open web (it would silently
break the promise that it used only the reader's files), and there is exactly
one retry, not a loop."""

from notekit.graph import MAX_BROADEN_ATTEMPTS, REFUSAL_FRACTION_TO_RETRY, _should_broaden
from notekit.models import ModuleNotes


def notes(refused: bool) -> ModuleNotes:
    return ModuleNotes(
        module_title="Module",
        body="" if refused else "Some cited notes.",
        cited_chunk_ids=[],
        chunks=[],
        refused=refused,
    )


def state(*, notes_dict, attempts=1, namespace=None):
    return {
        "notes": notes_dict,
        "attempts": attempts,
        "namespace": namespace,
    }


def test_no_notes_yet_means_finish():
    assert _should_broaden(state(notes_dict={}, attempts=0)) == "finish"


def test_below_the_refusal_fraction_finishes_without_retrying():
    # 1 of 4 refused = 25%, under the 40% bar.
    notes_dict = {0: notes(True), 1: notes(False), 2: notes(False), 3: notes(False)}
    assert _should_broaden(state(notes_dict=notes_dict)) == "finish"


def test_at_or_above_the_refusal_fraction_broadens():
    # 2 of 4 refused = 50%, at/above the 40% bar.
    notes_dict = {0: notes(True), 1: notes(True), 2: notes(False), 3: notes(False)}
    assert _should_broaden(state(notes_dict=notes_dict)) == "broaden"


def test_exactly_at_the_threshold_counts_as_broaden():
    # 2 of 5 = exactly REFUSAL_FRACTION_TO_RETRY (0.4); >= means it counts.
    assert REFUSAL_FRACTION_TO_RETRY == 0.4
    notes_dict = {i: notes(i < 2) for i in range(5)}
    assert _should_broaden(state(notes_dict=notes_dict)) == "broaden"


def test_no_refusals_at_all_finishes():
    notes_dict = {0: notes(False), 1: notes(False)}
    assert _should_broaden(state(notes_dict=notes_dict)) == "finish"


def test_all_refused_still_broadens_once():
    notes_dict = {0: notes(True), 1: notes(True)}
    assert _should_broaden(state(notes_dict=notes_dict, attempts=1)) == "broaden"


def test_uploaded_material_never_broadens_even_when_thin():
    # The guard: an explicit namespace means "use only what's already here".
    # High refusal on the reader's own files must not trigger a fetch from
    # the open web.
    notes_dict = {0: notes(True), 1: notes(True)}
    result = _should_broaden(
        state(notes_dict=notes_dict, attempts=1, namespace="user-sriya-ml")
    )
    assert result == "finish"


def test_retry_budget_is_exhausted_after_max_attempts():
    assert MAX_BROADEN_ATTEMPTS == 1
    notes_dict = {0: notes(True), 1: notes(True)}
    # attempts > MAX_BROADEN_ATTEMPTS: the retry has already happened once.
    result = _should_broaden(state(notes_dict=notes_dict, attempts=2))
    assert result == "finish"


def test_first_attempt_is_still_allowed_to_retry():
    notes_dict = {0: notes(True), 1: notes(True)}
    result = _should_broaden(state(notes_dict=notes_dict, attempts=1))
    assert result == "broaden"
