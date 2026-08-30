"""Export a finished course as a folder of Markdown notes.

The output is plain Markdown and opens in any editor, but it is shaped for
Obsidian, because Obsidian is where the shape pays off. Every source document
becomes its own note, every retrieved passage carries a block id, and every
`[c123]` marker in the prose becomes a footnote linking to that exact passage.
The graph view then draws the evidence structure: a section whose claims all
trace to one source shows up as a node with a single inbound edge, which is
the kind of thing the web reader cannot show you.

Nothing here calls a model or touches retrieval. It reads a saved course and
writes files, so the formatting is deterministic and testable on its own — the
functions that build note text take plain dicts and return strings, and only
`export_course` touches the filesystem.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Characters that are illegal in filenames on some OS, plus the ones that would
# break a wiki-link if they appeared inside one. `#` and `^` are link syntax,
# `|` is the alias separator, `[]` delimit the link itself.
_UNSAFE = re.compile(r'[\\/:*?"<>|\[\]#^]')
_WS = re.compile(r"\s+")
_CITATION = re.compile(r"\[c(\d+)\]")

# Long enough to stay readable, short enough to survive path limits once the
# vault path and folders are prepended.
_MAX_STEM = 80


def sanitize_filename(title: str, *, fallback: str = "untitled") -> str:
    """A note name that is safe on disk and inside a wiki-link."""
    cleaned = _UNSAFE.sub(" ", title or "")
    cleaned = _WS.sub(" ", cleaned).strip(" .")
    if len(cleaned) > _MAX_STEM:
        cleaned = cleaned[:_MAX_STEM].rstrip(" .")
    return cleaned or fallback


def _unique(name: str, taken: set[str]) -> str:
    """Disambiguate two sources that sanitise to the same note name."""
    if name not in taken:
        taken.add(name)
        return name
    n = 2
    while f"{name} ({n})" in taken:
        n += 1
    final = f"{name} ({n})"
    taken.add(final)
    return final


def _yaml_value(value: Any) -> str:
    """Quote anything that YAML would otherwise misread."""
    text = str(value)
    if text == "":
        return '""'
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def frontmatter(fields: dict[str, Any]) -> str:
    lines = ["---"]
    for key, value in fields.items():
        if value is None or value == [] or value == "":
            continue
        if isinstance(value, list):
            inner = ", ".join(str(v) for v in value)
            lines.append(f"{key}: [{inner}]")
        elif isinstance(value, bool):
            lines.append(f"{key}: {'true' if value else 'false'}")
        elif isinstance(value, (int, float)):
            lines.append(f"{key}: {value}")
        else:
            lines.append(f"{key}: {_yaml_value(value)}")
    lines.append("---")
    return "\n".join(lines)


@dataclass
class SourceNote:
    """One cited document, and the passages the course actually used."""

    note_name: str
    title: str
    url: str | None
    # chunk id -> passage text, in the order they were retrieved.
    passages: dict[int, str] = field(default_factory=dict)


def collect_sources(course: dict) -> tuple[dict[int, SourceNote], list[SourceNote]]:
    """Map every chunk id to the source note it belongs to.

    Chunks are grouped by document, so ten passages from one Wikipedia article
    become one note with ten block ids rather than ten notes. That grouping is
    what makes the graph readable: edge count to a source then means "how many
    claims rest on this document".
    """
    by_document: dict[tuple[str, str | None], SourceNote] = {}
    by_chunk: dict[int, SourceNote] = {}
    taken: set[str] = set()

    for module in course.get("modules") or []:
        notes = module.get("notes") or {}
        for chunk in notes.get("chunks") or []:
            title = chunk.get("document_title") or "Untitled source"
            url = chunk.get("document_url")
            key = (title, url)
            source = by_document.get(key)
            if source is None:
                source = SourceNote(
                    note_name=_unique(sanitize_filename(title, fallback="source"), taken),
                    title=title,
                    url=url,
                )
                by_document[key] = source
            cid = int(chunk["id"])
            source.passages.setdefault(cid, chunk.get("text") or "")
            by_chunk[cid] = source

    return by_chunk, list(by_document.values())


def rewrite_citations(
    body: str, by_chunk: dict[int, SourceNote]
) -> tuple[str, list[int]]:
    """Turn `[c123]` markers into footnote references.

    Footnotes rather than inline links on purpose: the reader already decided
    that citations should not fight the prose (hence superscripts in the web
    UI), and a footnote marker is the Markdown equivalent of a superscript.

    A marker whose chunk is not in the course — a hallucinated id, or one
    dropped when the course was slimmed — is left as literal text rather than
    turned into a footnote that resolves to nothing. Better a visible oddity
    than a silent dangling reference.
    """
    used: list[int] = []

    def replace(match: re.Match[str]) -> str:
        cid = int(match.group(1))
        if cid not in by_chunk:
            return match.group(0)
        if cid not in used:
            used.append(cid)
        return f"[^c{cid}]"

    return _CITATION.sub(replace, body), used


def _footnote_block(used: list[int], by_chunk: dict[int, SourceNote]) -> str:
    """Footnote definitions, each linking to the exact passage it cites."""
    lines = []
    for cid in used:
        source = by_chunk[cid]
        # Block-reference link: Obsidian resolves `#^c123` to the passage in
        # the source note carrying that block id.
        link = f"[[Sources/{source.note_name}#^c{cid}|{source.title}]]"
        lines.append(f"[^c{cid}]: {link}")
    return "\n".join(lines)


def _quiz_block(
    quiz: dict | None, by_chunk: dict[int, SourceNote], used: list[int]
) -> str:
    """Practice questions as collapsed callouts, so answers stay hidden.

    `> [!question]-` is an Obsidian callout that starts folded. Anywhere else
    it degrades to an ordinary blockquote, which is still readable.

    Explanations carry `[c123]` markers just as the prose does, so they get the
    same footnote treatment — `used` is appended to in place so their sources
    reach the footnote block at the bottom of the note.
    """
    if not quiz or not quiz.get("questions"):
        return ""
    out = ["## Practice questions", ""]
    for i, q in enumerate(quiz["questions"], 1):
        options = q.get("options") or []
        answer_index = q.get("answer_index")
        out.append(f"> [!question]- {i}. {q.get('question', '').strip()}")
        for letter, option in zip("ABCD", options):
            out.append(f"> - **{letter}.** {option}")
        if isinstance(answer_index, int) and 0 <= answer_index < len(options):
            out.append("> ")
            out.append(f"> **Answer: {'ABCD'[answer_index]}.** {options[answer_index]}")
        explanation = (q.get("explanation") or "").strip()
        if explanation:
            rewritten, cited = rewrite_citations(explanation, by_chunk)
            for cid in cited:
                if cid not in used:
                    used.append(cid)
            out.append("> ")
            out.append(f"> {rewritten}")
        out.append("")
    return "\n".join(out).rstrip()


def module_note(
    course: dict,
    module: dict,
    *,
    goals: list[str],
    by_chunk: dict[int, SourceNote],
) -> str:
    """One section of the course, as a note."""
    notes = module.get("notes") or {}
    index = int(module.get("index", 0)) + 1
    total = len(course.get("modules") or [])
    title = notes.get("module_title") or module.get("title") or f"Section {index}"

    head = frontmatter(
        {
            "course": course.get("title") or course.get("goal"),
            "section": index,
            "of": total,
            "refused": bool(notes.get("refused")) or None,
            "tags": ["notekit"],
        }
    )

    parts = [head, "", f"# {title}", ""]

    if goals:
        parts.append("> [!info] Learning goals")
        parts.extend(f"> - {g}" for g in goals)
        parts.append("")

    if notes.get("refused"):
        # A refusal is a result, not an error, and it should survive export as
        # plainly as it appears in the app.
        reason = notes.get("refusal_reason") or "The sources did not cover this."
        parts.append("> [!warning] Not enough source material")
        parts.append(f"> {reason}")
        parts.append("")
        return "\n".join(parts).rstrip() + "\n"

    body, used = rewrite_citations(notes.get("body") or "", by_chunk)
    parts.append(body.strip())
    parts.append("")

    # Appends any citations the explanations introduce to `used`, so the
    # footnote block below covers the quiz too.
    quiz = _quiz_block(notes.get("quiz"), by_chunk, used)
    if quiz:
        parts.extend([quiz, ""])

    if used:
        parts.append("## Sources")
        parts.append("")
        parts.append(_footnote_block(used, by_chunk))

    return "\n".join(parts).rstrip() + "\n"


def source_note(source: SourceNote) -> str:
    """One cited document, with each used passage carrying a block id.

    The block id is what makes a citation land on the passage rather than the
    top of the file, so a claim can be checked without leaving the vault.
    """
    head = frontmatter(
        {
            "title": source.title,
            "url": source.url,
            "tags": ["notekit", "source"],
        }
    )
    parts = [head, "", f"# {source.title}", ""]
    if source.url:
        parts.extend([f"<{source.url}>", ""])
    parts.append("## Cited passages")
    parts.append("")
    for cid, text in source.passages.items():
        # The block id must be the last thing in the block for Obsidian to
        # attach it, and the passage is collapsed to one paragraph so the id
        # binds to the whole thing rather than its final line.
        flattened = _WS.sub(" ", (text or "").strip())
        parts.append(f"{flattened} ^c{cid}")
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def course_index(course: dict, module_names: list[str], sources: list[SourceNote]) -> str:
    """The note you open first: what this course is, and links into it."""
    title = course.get("title") or course.get("goal") or "Course"
    head = frontmatter(
        {
            "goal": course.get("goal"),
            "sections": len(module_names),
            "words": course.get("word_count") or None,
            "created": (course.get("created_at") or "")[:10] or None,
            "tags": ["notekit", "course"],
        }
    )

    parts = [head, "", f"# {title}", ""]
    summary = (course.get("summary") or "").strip()
    if summary:
        parts.extend([summary, ""])

    parts.append("## Sections")
    parts.append("")
    for i, name in enumerate(module_names, 1):
        parts.append(f"{i}. [[{name}]]")
    parts.append("")

    if sources:
        parts.append(f"## Sources ({len(sources)})")
        parts.append("")
        for source in sorted(sources, key=lambda s: s.title.lower()):
            parts.append(f"- [[Sources/{source.note_name}|{source.title}]]")
    return "\n".join(parts).rstrip() + "\n"


@dataclass
class ExportResult:
    folder: Path
    index: Path
    modules: list[Path]
    sources: list[Path]

    @property
    def file_count(self) -> int:
        return 1 + len(self.modules) + len(self.sources)


def _goals_for(course: dict, index: int) -> list[str]:
    """Learning goals live on the syllabus, not the saved module."""
    syllabus = course.get("syllabus") or {}
    modules = syllabus.get("modules") or []
    if 0 <= index < len(modules):
        return list(modules[index].get("learning_goals") or [])
    return []


def export_course(course: dict, destination: str | Path) -> ExportResult:
    """Write the course into `destination/<course title>/`.

    The only function here that touches disk. Existing files are overwritten,
    so re-exporting a course after reading it is safe and idempotent.
    """
    title = course.get("title") or course.get("goal") or "Course"
    folder = Path(destination).expanduser() / sanitize_filename(title, fallback="course")
    sources_dir = folder / "Sources"
    sources_dir.mkdir(parents=True, exist_ok=True)

    by_chunk, sources = collect_sources(course)

    module_paths: list[Path] = []
    module_names: list[str] = []
    for module in course.get("modules") or []:
        notes = module.get("notes") or {}
        index = int(module.get("index", 0))
        heading = notes.get("module_title") or module.get("title") or f"Section {index + 1}"
        name = f"{index + 1:02d} {sanitize_filename(heading, fallback='section')}"
        text = module_note(
            course, module, goals=_goals_for(course, index), by_chunk=by_chunk
        )
        path = folder / f"{name}.md"
        path.write_text(text, encoding="utf-8")
        module_paths.append(path)
        module_names.append(name)

    source_paths: list[Path] = []
    for source in sources:
        path = sources_dir / f"{source.note_name}.md"
        path.write_text(source_note(source), encoding="utf-8")
        source_paths.append(path)

    index_path = folder / f"{sanitize_filename(title, fallback='course')}.md"
    index_path.write_text(
        course_index(course, module_names, sources), encoding="utf-8"
    )

    return ExportResult(
        folder=folder,
        index=index_path,
        modules=module_paths,
        sources=source_paths,
    )
