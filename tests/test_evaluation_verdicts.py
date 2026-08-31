"""The faithfulness judge degenerates now and then, running into max_tokens and
returning truncated JSON. That raises while parsing, so it kills a whole eval
run rather than costing one module its score. These cover the recovery: retry,
then split, and above all that a split half's verdicts land back on the right
claims."""

import pytest
from pydantic import ValidationError

from notekit import evaluation


def truncated() -> ValidationError:
    """A real parse failure of the shape the judge actually produces."""
    with pytest.raises(ValidationError) as caught:
        evaluation._Verdicts.model_validate_json('{"verdicts": [{"claim_in')
    return caught.value


def verdicts_for(n: int, *, supported: bool = True):
    """A well-formed response covering claims 1..n in local numbering."""
    return evaluation._Verdicts(
        verdicts=[
            evaluation._Verdict(claim_index=i, supported=supported, reason="r")
            for i in range(1, n + 1)
        ]
    )


def fake_parse(monkeypatch, handler):
    calls: list[int] = []

    def parse(**kwargs):
        n = len([ln for ln in kwargs["prompt"].splitlines() if ln[:1].isdigit()])
        calls.append(n)
        return handler(n, len(calls))

    monkeypatch.setattr(evaluation.llm, "parse", parse)
    return calls


def test_a_clean_response_maps_every_claim(monkeypatch):
    fake_parse(monkeypatch, lambda n, call: verdicts_for(n))
    got = evaluation._verdicts_for(["a", "b", "c"], "passages")
    assert sorted(got) == [1, 2, 3]


def test_one_bad_response_is_retried_not_fatal(monkeypatch):
    calls = fake_parse(
        monkeypatch,
        lambda n, call: verdicts_for(n) if call > 1 else (_ for _ in ()).throw(truncated()),
    )
    got = evaluation._verdicts_for(["a", "b"], "passages")
    assert sorted(got) == [1, 2]
    assert len(calls) == 2, "should retry exactly once before splitting"


def test_a_split_half_keeps_the_callers_numbering(monkeypatch):
    # The failure mode this guards: the second half is judged with local
    # indices 1..2, and without the offset its verdicts would overwrite the
    # first half's, scoring claims 3 and 4 against claims 1 and 2's judgements.
    def handler(n, call):
        if n == 4:
            raise truncated()
        return evaluation._Verdicts(
            verdicts=[
                evaluation._Verdict(claim_index=i, supported=(i == 1), reason="r")
                for i in range(1, n + 1)
            ]
        )

    calls = fake_parse(monkeypatch, handler)
    got = evaluation._verdicts_for(["a", "b", "c", "d"], "passages")

    assert sorted(got) == [1, 2, 3, 4]
    assert calls == [4, 4, 2, 2], "initial, retry, then two halves"
    # Each half marked only its own first claim supported: globally 1 and 3.
    assert [i for i, v in sorted(got.items()) if v.supported] == [1, 3]


def test_a_single_unjudgeable_claim_raises_rather_than_scoring_zero(monkeypatch):
    # Marking it unsupported would quietly understate faithfulness.
    fake_parse(monkeypatch, lambda n, call: (_ for _ in ()).throw(truncated()))
    with pytest.raises(ValidationError):
        evaluation._verdicts_for(["only one"], "passages")


def test_an_out_of_range_index_is_dropped(monkeypatch):
    # Offsetting a bogus index would land it on another half's claim.
    fake_parse(
        monkeypatch,
        lambda n, call: evaluation._Verdicts(
            verdicts=[
                evaluation._Verdict(claim_index=1, supported=True, reason="r"),
                evaluation._Verdict(claim_index=99, supported=True, reason="r"),
            ]
        ),
    )
    got = evaluation._verdicts_for(["a", "b"], "passages")
    assert sorted(got) == [1]
