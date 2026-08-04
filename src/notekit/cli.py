"""Terminal interface. Milestone 3 adds the full eval sweep here."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

from . import config, db, ingest, llm, retrieval
from .pipeline import run_course

app = typer.Typer(add_completion=False, help="Grounded course-notes agent")
console = Console()


@app.command("ingest")
def ingest_cmd(
    topic: str = typer.Argument(..., help="Topic to fetch sources for"),
    limit: int = typer.Option(10, help="Maximum documents to fetch"),
) -> None:
    """Fetch and index a corpus. Needs no API key."""
    slug = topic.lower().replace(" ", "-")
    summary = ingest.ingest_topic(slug=slug, query=topic, namespace=slug, limit=limit)

    if summary.get("cached"):
        console.print(f"[yellow]Already ingested[/] — {summary['chunks']} chunks.")
    else:
        console.print(
            f"[green]Indexed[/] {summary['new_documents']} documents, "
            f"{summary['new_chunks']} chunks into namespace [bold]{slug}[/]."
        )


@app.command("search")
def search_cmd(
    query: str = typer.Argument(..., help="Retrieval query"),
    namespace: str = typer.Option(..., "--namespace", "-n"),
) -> None:
    """Run one retrieval and print what comes back. Needs no API key."""
    chunks = retrieval.retrieve(query=query, namespace=namespace)
    if not chunks:
        console.print("[red]Nothing retrieved.[/] Is the namespace ingested?")
        raise typer.Exit(1)

    for c in chunks:
        console.print(f"[bold cyan]{c.citation_key}[/] score={c.score:.2f} — {c.document_title}")
        console.print(f"  {c.text[:200].strip()}...\n")


@app.command("course")
def course_cmd(
    goal: str = typer.Argument(..., help="e.g. 'teach me Q-learning at an intermediate level'"),
    limit: int = typer.Option(10, help="Maximum documents to ingest if the topic is new"),
    skip_ingest: bool = typer.Option(False, help="Assume the corpus already exists"),
) -> None:
    """Plan a syllabus and write cited notes for every module."""
    llm.reset_usage()
    syllabus, notes = run_course(goal, limit=limit, skip_ingest=skip_ingest)

    console.print(f"\n[bold]{syllabus.summary}[/]")
    console.print(f"[dim]namespace: {syllabus.topic_slug}[/]\n")

    for module in notes:
        console.rule(f"[bold]{module.module_title}")
        if module.refused:
            console.print("[yellow]Not covered by the sources.[/]")
            # markup=False: reasons can contain [c123] citation markers, which
            # Rich would otherwise parse as style tags and silently drop.
            console.print(module.refusal_reason or "", markup=False)
            console.print()
            continue

        console.print(Markdown(module.body))
        sources = {c.id: c for c in module.chunks}
        console.print("\n[dim]Sources cited:[/]")
        for chunk_id in module.cited_chunk_ids:
            c = sources[chunk_id]
            console.print(f"  [cyan]{c.citation_key}[/] {c.document_title} — {c.document_url}")
        console.print()

    _print_usage()


@app.command("stats")
def stats_cmd(namespace: str = typer.Argument(...)) -> None:
    """Show what is indexed in a namespace."""
    with db.connect() as conn:
        stats = db.namespace_stats(conn, namespace)
    console.print(f"{stats['documents']} documents, {stats['chunks']} chunks.")


def _print_usage() -> None:
    entries, total = llm.usage_report()
    if not entries:
        return

    table = Table(title="Token usage", title_style="dim")
    for column in ("model", "input", "cache write", "cache read", "output"):
        table.add_column(column)
    for e in entries:
        table.add_row(
            e.model,
            f"{e.input_tokens:,}",
            f"{e.cache_write_tokens:,}",
            f"{e.cache_read_tokens:,}",
            f"{e.output_tokens:,}",
        )
    console.print(table)
    console.print(f"[dim]Estimated cost: ${total:.4f}[/]")


if __name__ == "__main__":
    app()
