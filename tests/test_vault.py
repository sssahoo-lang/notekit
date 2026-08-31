"""Markdown/Obsidian export.

The whole point of the export is that a citation still resolves after it
leaves the app, so most of these tests are about that chain holding: a
`[c123]` marker becomes a footnote, the footnote links to a source note, and
the source note carries a matching block id. Break any link in that chain and
the feature is decoration.

Everything except `export_course` is a pure function over dicts, so this runs
with no database and no API key.
"""

import pytest

from notekit import vault


def chunk(cid: int, *, title="Knowledge graph", url="https://example.org/kg", text="Passage text."):
    return {
        "id": cid,
        "text": text,
        "document_title": title,
        "document_url": url,
        "score": 1.0,
    }


def course(*, modules=None, **overrides):
    base = {
        "id": 1,
        "title": "Knowledge Graphs: From Basics",
        "goal": "knowledge graphs from basics",
        "summary": "An introduction.",
        "word_count": 100,
        "created_at": "2026-08-06T17:28:53+00:00",
        "modules": modules if modules is not None else [],
        "syllabus": {"modules": []},
    }
    base.update(overrides)
    return base


def module(*, index=0, title="Structure", body="Text.", chunks=None, **overrides):
    notes = {
        "module_title": title,
        "body": body,
        "chunks": chunks if chunks is not None else [],
        "cited_chunk_ids": [],
        "refused": False,
        "refusal_reason": None,
        "quiz": None,
    }
    notes.update(overrides.pop("notes", {}))
    return {"index": index, "title": title, "notes": notes, "error": None}


# --------------------------------------------------------------------------
# filenames
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Knowledge graph", "Knowledge graph"),
        # Illegal on some filesystems.
        ("Knowledge Graphs: A Survey", "Knowledge Graphs A Survey"),
        ("a/b\\c", "a b c"),
        ('quote" star* question?', "quote star question"),
        # Would break a wiki-link from the inside.
        ("Title [with] brackets", "Title with brackets"),
        ("Header # and ^ caret", "Header and caret"),
        ("Pipe | separator", "Pipe separator"),
    ],
)
def test_sanitize_filename_strips_unsafe_and_link_breaking_characters(raw, expected):
    assert vault.sanitize_filename(raw) == expected


def test_sanitize_filename_falls_back_when_nothing_survives():
    assert vault.sanitize_filename("") == "untitled"
    assert vault.sanitize_filename("///") == "untitled"
    assert vault.sanitize_filename("...") == "untitled"


def test_sanitize_filename_truncates_long_titles():
    name = vault.sanitize_filename("A" * 200)
    assert len(name) <= 80


def test_sanitize_filename_does_not_end_in_a_dot_or_space():
    # A trailing dot or space is silently dropped by Windows and makes the
    # filename disagree with the link that points at it.
    assert not vault.sanitize_filename("Trailing dot.").endswith(".")
    assert not vault.sanitize_filename("Trailing space ").endswith(" ")


# --------------------------------------------------------------------------
# source collection
# --------------------------------------------------------------------------

def test_passages_from_one_document_group_into_one_source_note():
    c = course(modules=[module(chunks=[chunk(1), chunk(2), chunk(3)])])
    by_chunk, sources = vault.collect_sources(c)
    assert len(sources) == 1
    assert set(sources[0].passages) == {1, 2, 3}
    # Every chunk maps back to that one note.
    assert {id(by_chunk[i]) for i in (1, 2, 3)} == {id(sources[0])}


def test_different_documents_become_different_source_notes():
    c = course(modules=[module(chunks=[
        chunk(1, title="Knowledge graph"),
        chunk(2, title="Graph database"),
    ])])
    _, sources = vault.collect_sources(c)
    assert sorted(s.title for s in sources) == ["Graph database", "Knowledge graph"]


def test_the_same_document_cited_from_two_modules_is_one_note():
    c = course(modules=[
        module(index=0, chunks=[chunk(1)]),
        module(index=1, chunks=[chunk(2)]),
    ])
    _, sources = vault.collect_sources(c)
    assert len(sources) == 1
    assert set(sources[0].passages) == {1, 2}


def test_documents_that_sanitise_to_the_same_name_get_distinct_notes():
    # Two genuinely different papers whose titles collapse to the same string
    # must not overwrite each other's file.
    c = course(modules=[module(chunks=[
        chunk(1, title="Graphs: A Survey", url="https://a"),
        chunk(2, title="Graphs / A Survey", url="https://b"),
    ])])
    _, sources = vault.collect_sources(c)
    names = [s.note_name for s in sources]
    assert len(set(names)) == 2, names


# --------------------------------------------------------------------------
# citations
# --------------------------------------------------------------------------

def test_citation_markers_become_footnote_references():
    by_chunk, _ = vault.collect_sources(
        course(modules=[module(chunks=[chunk(12)])])
    )
    body, used = vault.rewrite_citations("A claim [c12].", by_chunk)
    assert body == "A claim [^c12]."
    assert used == [12]


def test_adjacent_citations_each_become_their_own_footnote():
    by_chunk, _ = vault.collect_sources(
        course(modules=[module(chunks=[chunk(1), chunk(2)])])
    )
    body, used = vault.rewrite_citations("Jointly supported [c1][c2].", by_chunk)
    assert body == "Jointly supported [^c1][^c2]."
    assert used == [1, 2]


def test_a_citation_repeated_is_only_listed_once():
    by_chunk, _ = vault.collect_sources(
        course(modules=[module(chunks=[chunk(7)])])
    )
    body, used = vault.rewrite_citations("One [c7]. Two [c7].", by_chunk)
    assert body == "One [^c7]. Two [^c7]."
    assert used == [7]


def test_an_unknown_citation_id_is_left_as_literal_text():
    # A hallucinated or dropped id must not become a footnote that resolves to
    # nothing. A visible oddity beats a silent dangling reference.
    by_chunk, _ = vault.collect_sources(
        course(modules=[module(chunks=[chunk(1)])])
    )
    body, used = vault.rewrite_citations("Real [c1], bogus [c9999].", by_chunk)
    assert body == "Real [^c1], bogus [c9999]."
    assert used == [1]


def test_body_without_citations_is_unchanged():
    body, used = vault.rewrite_citations("No citations here.", {})
    assert body == "No citations here."
    assert used == []


# --------------------------------------------------------------------------
# note bodies
# --------------------------------------------------------------------------

def test_module_note_links_each_footnote_to_the_passage_block():
    c = course(modules=[module(body="A claim [c12].", chunks=[chunk(12)])])
    by_chunk, _ = vault.collect_sources(c)
    text = vault.module_note(c, c["modules"][0], goals=[], by_chunk=by_chunk)
    assert "[^c12]: [[Sources/Knowledge graph#^c12|Knowledge graph]]" in text


def test_module_note_carries_learning_goals():
    c = course(modules=[module()])
    text = vault.module_note(
        c, c["modules"][0], goals=["Define a triple"], by_chunk={}
    )
    assert "Learning goals" in text
    assert "> - Define a triple" in text


def test_a_refused_module_exports_the_refusal_not_an_empty_note():
    # Refusing is a result, and it should survive export as plainly as it
    # appears in the app.
    m = module(body="", notes={"refused": True, "refusal_reason": "Sources too thin."})
    c = course(modules=[m])
    text = vault.module_note(c, m, goals=[], by_chunk={})
    assert "Not enough source material" in text
    assert "Sources too thin." in text
    assert "## Sources" not in text


def test_mermaid_diagrams_pass_through_untouched():
    # Obsidian renders mermaid natively, so the fenced block should survive
    # exactly as written.
    body = "Before.\n\n```mermaid\nflowchart LR\n  A[State] --> B[Action]\n```\n\nAfter."
    c = course(modules=[module(body=body)])
    text = vault.module_note(c, c["modules"][0], goals=[], by_chunk={})
    assert "```mermaid\nflowchart LR\n  A[State] --> B[Action]\n```" in text


def test_quiz_citations_are_footnoted_like_the_prose():
    quiz = {"questions": [{
        "question": "What?",
        "options": ["a", "b", "c", "d"],
        "answer_index": 0,
        "explanation": "Because the passage says so [c12].",
    }]}
    c = course(modules=[module(body="Body [c12].", chunks=[chunk(12)], notes={"quiz": quiz})])
    by_chunk, _ = vault.collect_sources(c)
    text = vault.module_note(c, c["modules"][0], goals=[], by_chunk=by_chunk)
    assert "[c12]" not in text.replace("[^c12]", "")  # no raw markers left
    assert "**Answer: A.**" in text


def test_quiz_only_citation_still_gets_a_footnote_definition():
    # The explanation cites something the prose never did; its definition must
    # still reach the footnote block or the reference dangles.
    quiz = {"questions": [{
        "question": "What?",
        "options": ["a", "b", "c", "d"],
        "answer_index": 1,
        "explanation": "See [c99].",
    }]}
    c = course(modules=[module(body="No citations.", chunks=[chunk(99)], notes={"quiz": quiz})])
    by_chunk, _ = vault.collect_sources(c)
    text = vault.module_note(c, c["modules"][0], goals=[], by_chunk=by_chunk)
    assert "[^c99]:" in text


def test_source_note_gives_every_passage_a_block_id():
    _, sources = vault.collect_sources(
        course(modules=[module(chunks=[chunk(1), chunk(2)])])
    )
    text = vault.source_note(sources[0])
    assert "^c1" in text
    assert "^c2" in text


def test_source_note_flattens_passages_so_the_block_id_binds():
    # A block id attaches to the block it terminates. If the passage kept its
    # internal newlines the id would bind to the last line only.
    _, sources = vault.collect_sources(
        course(modules=[module(chunks=[chunk(1, text="Line one.\n\nLine two.")])])
    )
    text = vault.source_note(sources[0])
    assert "Line one. Line two. ^c1" in text


# --------------------------------------------------------------------------
# frontmatter
# --------------------------------------------------------------------------

def test_frontmatter_quotes_values_that_yaml_would_misread():
    out = vault.frontmatter({"course": "Graphs: From Basics"})
    assert 'course: "Graphs: From Basics"' in out


def test_frontmatter_escapes_embedded_quotes():
    out = vault.frontmatter({"title": 'He said "hi"'})
    assert r'title: "He said \"hi\""' in out


def test_frontmatter_omits_empty_values():
    out = vault.frontmatter({"a": 1, "b": None, "c": "", "d": []})
    assert "a: 1" in out
    for absent in ("b:", "c:", "d:"):
        assert absent not in out


# --------------------------------------------------------------------------
# writing to disk
# --------------------------------------------------------------------------

def test_export_writes_index_modules_and_sources(tmp_path):
    c = course(modules=[
        module(index=0, title="Structure", body="A [c1].", chunks=[chunk(1)]),
        module(index=1, title="Storage", body="B [c2].",
               chunks=[chunk(2, title="Graph database", url="https://gd")]),
    ])
    result = vault.export_course(c, tmp_path)

    assert result.index.exists()
    assert len(result.modules) == 2
    assert len(result.sources) == 2
    assert result.file_count == 5
    assert all(p.exists() for p in result.modules + result.sources)


def test_exported_module_filenames_are_ordered(tmp_path):
    c = course(modules=[
        module(index=0, title="First"),
        module(index=1, title="Second"),
    ])
    result = vault.export_course(c, tmp_path)
    assert [p.name for p in result.modules] == ["01 First.md", "02 Second.md"]


def test_export_is_idempotent(tmp_path):
    # Re-exporting after reading a course should overwrite cleanly rather than
    # accumulate duplicates.
    c = course(modules=[module(body="A [c1].", chunks=[chunk(1)])])
    first = vault.export_course(c, tmp_path)
    text_before = first.index.read_text()
    second = vault.export_course(c, tmp_path)

    assert second.index == first.index
    assert second.index.read_text() == text_before
    assert len(list(second.folder.glob("*.md"))) == 2  # index + one module


def test_every_footnote_reference_has_a_definition(tmp_path):
    """The end-to-end invariant: no dangling references anywhere."""
    import re

    c = course(modules=[
        module(index=0, body="A [c1] and [c2].", chunks=[chunk(1), chunk(2)]),
    ])
    result = vault.export_course(c, tmp_path)
    for path in result.modules:
        text = path.read_text()
        refs = set(re.findall(r"\[\^(c\d+)\](?!:)", text))
        defs = set(re.findall(r"^\[\^(c\d+)\]:", text, re.M))
        assert refs == defs, f"{path.name}: {refs ^ defs} unmatched"


def test_every_block_link_lands_on_a_real_passage(tmp_path):
    """A citation that does not resolve makes the whole feature decoration."""
    import re

    c = course(modules=[module(body="A [c1].", chunks=[chunk(1)])])
    result = vault.export_course(c, tmp_path)
    text = result.modules[0].read_text()
    links = re.findall(r"\[\[Sources/([^\]|#]+)#\^(c\d+)\|", text)
    assert links, "expected at least one block-reference link"
    for note_name, block in links:
        target = result.folder / "Sources" / f"{note_name}.md"
        assert target.exists(), f"missing source note {note_name}"
        assert f"^{block}" in target.read_text()
