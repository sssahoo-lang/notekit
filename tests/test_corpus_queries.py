"""Which queries a topic's corpus gets built from.

The subject-level query was the slug, which is what the reader typed reduced
to kebab-case. "system design" matched "design" and "system" independently and
returned Cadence Design Systems, Fluent Design System, instructional design,
design-build construction, inverse design of polypills, and a fusion reactor
heat exhaust study. Four documents in twenty were about the subject, and the
notes then had to keep reporting that the passages did not cover what the
section was supposed to teach.

The planner now writes that query the same way it writes each module's."""

from notekit.models import Module, Syllabus
from notekit.pipeline import corpus_queries


def syllabus(**over) -> Syllabus:
    base = dict(
        title="System design",
        topic_slug="system-design",
        summary="A course.",
        corpus_query="distributed systems architecture scalability",
        modules=[
            Module(title="A", query="horizontal vertical scaling", learning_goals=["g"]),
            Module(title="B", query="CAP theorem replication", learning_goals=["g"]),
        ],
    )
    base.update(over)
    return Syllabus(**base)


def test_the_subject_query_leads_and_the_modules_follow():
    assert corpus_queries(syllabus()) == [
        "distributed systems architecture scalability",
        "horizontal vertical scaling",
        "CAP theorem replication",
    ]


def test_the_slug_is_the_fallback_not_the_default():
    # Syllabi planned before this field existed still have to ingest, and the
    # slug is the only subject-level query they carry.
    assert corpus_queries(syllabus(corpus_query=""))[0] == "system design"
    assert corpus_queries(syllabus(corpus_query="   "))[0] == "system design"


def test_a_missing_field_does_not_break_an_old_fixture():
    # The field has a default so `notekit eval --syllabus` keeps working on
    # fixtures frozen before it was added.
    old = Syllabus(
        topic_slug="q-learning",
        summary="s",
        modules=[Module(title="A", query="td error", learning_goals=["g"])],
    )
    assert corpus_queries(old) == ["q learning", "td error"]


def test_a_duplicate_query_is_only_fetched_once():
    # The fetch budget is split across queries, so asking twice for the same
    # thing halves what everything else gets.
    dup = syllabus(corpus_query="CAP theorem replication")
    assert corpus_queries(dup) == [
        "CAP theorem replication",
        "horizontal vertical scaling",
    ]


def test_order_is_preserved_so_the_subject_is_never_starved():
    queries = corpus_queries(syllabus())
    assert queries[0] == "distributed systems architecture scalability"
