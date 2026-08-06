"""Terminal interface. Milestone 3 adds the full eval sweep here."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

from . import (
    calibration, config, db, evaluation, ingest, llm, retrieval, style, sweep, upload,
)
from .adapters import DEFAULT_ADAPTERS
from .models import Syllabus
from .pipeline import plan_syllabus, run_course

app = typer.Typer(add_completion=False, help="Grounded course-notes agent")
console = Console()


@app.command("ingest")
def ingest_cmd(
    topic: str = typer.Argument(..., help="Topic to fetch sources for"),
    limit: int = typer.Option(10, help="Maximum documents to fetch per source"),
    adapters: str = typer.Option(
        ",".join(DEFAULT_ADAPTERS), help="Comma-separated sources: wikipedia,arxiv"
    ),
    force: bool = typer.Option(False, help="Re-ingest even if the topic is cached"),
) -> None:
    """Fetch and index a corpus. Needs no API key."""
    slug = topic.lower().replace(" ", "-")
    summary = ingest.ingest_topic(
        slug=slug,
        query=topic,
        namespace=slug,
        limit=limit,
        adapter_names=[a.strip() for a in adapters.split(",") if a.strip()],
        force=force,
    )

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
    quiz: bool = typer.Option(False, help="Also generate a quiz per module"),
    namespace: str = typer.Option(
        None, "--namespace", "-n", help="Build only from this namespace (e.g. uploads)"
    ),
    user: str = typer.Option(
        None, "--user", "-u", help="Write in this user's learned style"
    ),
) -> None:
    """Plan a syllabus and write cited notes for every module."""
    llm.reset_usage()

    profile = style.load(user) if user else None
    if user and not profile:
        console.print(
            f"[yellow]No style profile for {user}; writing in the default voice. "
            f"Run `notekit style learn` first.[/]"
        )
    elif profile:
        console.print(f"[dim]style: {user}[/]")

    syllabus, notes = run_course(
        goal,
        limit=limit,
        skip_ingest=skip_ingest,
        with_quiz=quiz,
        namespace=namespace,
        style=profile,
    )

    console.print(f"\n[bold]{syllabus.summary}[/]")
    console.print(f"[dim]namespace: {namespace or syllabus.topic_slug}[/]\n")

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

        if module.quiz:
            console.print("[dim]Quiz:[/]")
            for i, q in enumerate(module.quiz.questions, 1):
                console.print(f"  [bold]{i}. {q.question}[/]", markup=False)
                for j, option in enumerate(q.options):
                    mark = "[green]*[/]" if j == q.answer_index else " "
                    console.print(f"    {mark} {chr(97 + j)}) {option}", markup=False)
                console.print(f"     [dim]{q.explanation}[/]", markup=False)
            console.print()

    _print_usage()


@app.command("upload")
def upload_cmd(
    paths: list[str] = typer.Argument(..., help="Files or directories to index"),
    user: str = typer.Option(..., "--user", "-u", help="User id owning this material"),
    topic: str = typer.Option("notes", help="Namespace suffix within this user"),
) -> None:
    """Index your own files into a private namespace. Needs no API key."""
    namespace = upload.user_namespace(user, topic)
    console.print(f"[dim]namespace: {namespace}[/]")

    try:
        summary = upload.ingest_files(paths, namespace=namespace)
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc

    if not summary["files"]:
        console.print("[yellow]No supported files found.[/]")
        raise typer.Exit(1)

    console.print(
        f"[green]Indexed[/] {summary['new_documents']} of {summary['files']} files, "
        f"{summary['new_chunks']} chunks."
    )
    for reason in summary["skipped"]:
        # Two prints: the label needs markup, the reason must not be parsed as
        # markup since filenames and messages can contain square brackets.
        console.print("  [yellow]skipped[/] ", end="")
        console.print(reason, markup=False, highlight=False)
    console.print(f"\nBuild a course from it:\n  notekit course \"...\" -n {namespace}")


style_app = typer.Typer(help="Learn and inspect writing styles")
app.add_typer(style_app, name="style")


@style_app.command("learn")
def style_learn_cmd(
    paths: list[str] = typer.Argument(..., help="Files holding a writing sample"),
    user: str = typer.Option(..., "--user", "-u", help="User id to save under"),
) -> None:
    """Learn how someone writes from a sample of their own writing.

    The sample is used once and not stored. Only a description of form is kept.
    """
    llm.reset_usage()
    try:
        files = upload.collect(paths)
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc

    samples = []
    for path in files:
        try:
            samples.append(upload.extract(path))
        except upload.UnsupportedFile as exc:
            console.print("  [yellow]skipped[/] ", end="")
            console.print(str(exc), markup=False, highlight=False)

    sample = "\n\n".join(samples)
    if not sample.strip():
        console.print("[red]No readable text in the sample.[/]")
        raise typer.Exit(1)

    try:
        profile = style.learn(sample)
    except ValueError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc

    style.save(user, profile, len(sample))
    console.print(f"[green]Learned style for[/] {user} from {len(sample):,} chars\n")
    _print_style(profile)
    _print_usage()


@style_app.command("show")
def style_show_cmd(
    user: str = typer.Option(..., "--user", "-u", help="User id"),
) -> None:
    """Show the stored style profile. Needs no API key."""
    profile = style.load(user)
    if not profile:
        console.print(f"[yellow]No style profile for {user}.[/]")
        raise typer.Exit(1)
    _print_style(profile)


def _print_style(profile: style.StyleProfile) -> None:
    console.print(profile.summary, markup=False, highlight=False)
    table = Table(show_header=False, title_style="dim")
    table.add_column("trait")
    table.add_column("value")
    for field in (
        "sentence_length", "structure", "formality", "person",
        "vocabulary", "uses_analogies", "uses_worked_examples", "uses_notation",
    ):
        table.add_row(field.replace("_", " "), str(getattr(profile, field)))
    console.print(table)
    for habit in profile.signature_habits:
        console.print(f"  · {habit}", markup=False, highlight=False)


@app.command("plan")
def plan_cmd(
    goal: str = typer.Argument(..., help="Learning goal to plan a syllabus for"),
    save: str = typer.Option(None, help="Write the syllabus to this JSON path"),
) -> None:
    """Plan a syllabus and optionally save it as an evaluation fixture."""
    llm.reset_usage()
    syllabus = plan_syllabus(goal)

    console.print(f"[bold]{syllabus.summary}[/]")
    console.print(f"[dim]slug: {syllabus.topic_slug}[/]\n")
    for i, module in enumerate(syllabus.modules, 1):
        console.print(f"[bold]{i}. {module.title}[/]")
        console.print(f"   [dim]query:[/] {module.query}")
        for goal_text in module.learning_goals:
            console.print(f"   - {goal_text}")

    if save:
        path = Path(save)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(syllabus.model_dump_json(indent=2))
        console.print(f"\n[green]Saved fixture:[/] {save}")

    _print_usage()


@app.command("calibrate")
def calibrate_cmd(
    evalset: str = typer.Argument(..., help="Path to a calibration set JSON"),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Persist the suggested threshold so generation uses it",
    ),
) -> None:
    """Find the refusal threshold that best separates covered from uncovered.

    Needs no API key — retrieval and reranking are local. Pass --apply to write
    the suggested value for the API and future CLI runs.
    """
    report = calibration.calibrate(
        calibration.CalibrationSet.load(evalset), apply=apply
    )

    table = Table(title="Refusal calibration", title_style="dim")
    for column in ("query", "expected", "top score"):
        table.add_column(column)
    for p in sorted(report.probes, key=lambda p: p.top_score or -99, reverse=True):
        table.add_row(
            p.query[:52],
            "covered" if p.expected_covered else "uncovered",
            f"{p.top_score:.2f}" if p.top_score is not None else "—",
        )
    console.print(table)

    if report.suggested_threshold is None:
        console.print("[red]No scores returned — is the namespace ingested?[/]")
        raise typer.Exit(1)

    console.print(
        f"\ncurrent threshold {report.current_threshold:+.2f} "
        f"→ accuracy {report.current_accuracy:.0%}"
    )
    console.print(
        f"suggested threshold {report.suggested_threshold:+.2f} "
        f"→ accuracy {report.accuracy:.0%}"
    )
    if report.applied:
        console.print(
            f"[green]Applied[/] → {report.applied_path} "
            f"(live threshold {config.refusal_score_threshold():+.2f})"
        )
    if report.separated:
        console.print("[green]Covered and uncovered questions separate cleanly.[/]")
    else:
        console.print(
            "[yellow]No threshold separates them perfectly — "
            "the overlapping questions are worth reading.[/]"
        )


@app.command("eval")
def eval_cmd(
    goal: str = typer.Argument("", help="Learning goal (ignored when --syllabus is given)"),
    syllabus_path: str = typer.Option(
        None, "--syllabus", help="Fixture JSON from `notekit plan --save`"
    ),
    skip_ingest: bool = typer.Option(True, help="Assume the corpus already exists"),
    explain: bool = typer.Option(False, help="Print every unsupported claim"),
    repeat: int = typer.Option(
        1, help="Run N times and report the spread. Coverage needs this."
    ),
    user: str = typer.Option(
        None, "--user", "-u", help="Score notes written in this user's style"
    ),
) -> None:
    """Generate a course, then score it for faithfulness and coverage.

    Pass --syllabus to hold the plan fixed. Without it the planner re-plans on
    every run, so two measurements cover different work and cannot be compared.

    Even with a fixed syllabus, coverage varies by tens of points run to run:
    there are only a handful of learning goals and the judge is not
    deterministic. Use --repeat before believing any single coverage figure.
    """
    if not goal and not syllabus_path:
        console.print("[red]Give a goal or a --syllabus fixture.[/]")
        raise typer.Exit(1)

    fixture = (
        Syllabus.model_validate_json(Path(syllabus_path).read_text())
        if syllabus_path
        else None
    )
    if fixture:
        console.print(f"[dim]fixture: {syllabus_path} ({len(fixture.modules)} modules)[/]")
    else:
        console.print(
            "[yellow]No fixture: the planner will re-plan, so this run is not "
            "comparable with any other.[/]"
        )

    profile = style.load(user) if user else None
    if user and not profile:
        console.print(f"[red]No style profile for {user}.[/]")
        raise typer.Exit(1)
    console.print(f"[dim]style: {user or 'none (default voice)'}[/]")

    llm.reset_usage()

    runs = []
    for n in range(repeat):
        if repeat > 1:
            console.print(f"[dim]run {n + 1}/{repeat}[/]")
        syllabus, notes = run_course(
            goal, skip_ingest=skip_ingest, syllabus=fixture, style=profile
        )
        results = evaluation.evaluate_course(notes, syllabus.modules)
        runs.append((results, evaluation.aggregate(results)))

    if repeat > 1:
        _print_spread(runs)
        _print_usage()
        return

    results, summary = runs[0]

    table = Table(title="Evaluation", title_style="dim")
    for column in ("module", "claims", "supported", "faithfulness", "coverage"):
        table.add_column(column)
    for r in results:
        if r.refused:
            table.add_row(r.module_title[:34], "—", "—", "[yellow]refused[/]", "—")
            continue
        table.add_row(
            r.module_title[:34],
            str(len(r.claims)),
            str(sum(c.supported for c in r.claims)),
            f"{r.faithfulness:.0%}" if r.faithfulness is not None else "—",
            f"{r.coverage_score:.0%}" if r.coverage_score is not None else "—",
        )
    console.print(table)

    faith = summary["faithfulness"]
    cov = summary["coverage"]
    console.print(
        f"\n[bold]faithfulness {faith:.1%}[/] "
        f"({summary['supported']}/{summary['claims']} claims supported)"
        if faith is not None
        else "\n[yellow]No claims scored.[/]"
    )
    if cov is not None:
        console.print(f"[bold]coverage {cov:.1%}[/]")
    console.print(
        f"[dim]{summary['refused']}/{summary['modules']} modules refused for "
        f"lack of source material[/]"
    )

    if explain:
        for r in results:
            for c in r.unsupported:
                console.print(f"\n[red]unsupported[/] ({r.module_title[:40]})")
                console.print(f"  claim: {c.claim}", markup=False)
                console.print(f"  why:   {c.reason}", markup=False)

    _print_usage()


@app.command("sweep")
def sweep_cmd(
    syllabus_path: str = typer.Option(
        ..., "--syllabus", help="Fixture JSON from `notekit plan --save`"
    ),
    namespace: str = typer.Option(..., "--namespace", "-n", help="Corpus to use"),
    repeat: int = typer.Option(1, help="Runs per configuration"),
    limit: int = typer.Option(
        0, help="Only the first N configurations. 0 runs all of them."
    ),
) -> None:
    """Compare the retrieval configurations in config.SWEEP on one syllabus.

    Costs roughly one evaluated course per configuration per repeat, so a full
    four-config sweep at --repeat 2 is eight courses. Start with --limit 2.
    """
    fixture = Syllabus.model_validate_json(Path(syllabus_path).read_text())
    configs = config.SWEEP[:limit] if limit else config.SWEEP

    console.print(
        f"[dim]{len(configs)} configurations x {repeat} run(s) on "
        f"'{namespace}' — about {len(configs) * repeat} courses[/]\n"
    )

    def progress(r: sweep.ConfigResult) -> None:
        if r.skipped:
            console.print(f"  [yellow]{r.name}[/] skipped — {r.skipped}")
        else:
            f = r.faithfulness
            console.print(
                f"  [green]{r.name}[/] "
                f"{f:.1%} over {r.claims} claims"
                if f is not None
                else f"  [yellow]{r.name}[/] no claims scored"
            )

    results = sweep.run_sweep(
        fixture,
        namespace=namespace,
        repeat=repeat,
        configs=configs,
        on_progress=progress,
    )

    table = Table(title="Retrieval configurations", title_style="dim")
    for column in ("config", "faithfulness", "spread", "claims", "cost"):
        table.add_column(column)
    for r in results:
        if r.skipped:
            table.add_row(r.name, "—", "—", "—", "—")
            continue
        table.add_row(
            r.name,
            f"{r.faithfulness:.1%}" if r.faithfulness is not None else "—",
            f"{r.spread * 100:.1f} pts" if r.spread is not None else "—",
            str(r.claims),
            f"${r.cost_usd:.2f}",
        )
    console.print(table)

    scored = [r for r in results if r.faithfulness is not None]
    if len(scored) > 1:
        spread = max(r.faithfulness for r in scored) - min(
            r.faithfulness for r in scored
        )
        within = max((r.spread or 0) for r in scored)
        console.print(f"\nBest minus worst: {spread * 100:.1f} pts.")
        if repeat < 2:
            # With one run per configuration there is no noise estimate at all,
            # so an ordering here says nothing. The fixture's own run-to-run
            # spread has been measured at 4.6 points, which is wider than most
            # gaps this sweep produces.
            console.print(
                "[yellow]One run per configuration measures no noise, so this "
                "ordering is not evidence. Repeated runs of a single "
                "configuration on this fixture have varied by 4.6 points — "
                "wider than most gaps above. Use --repeat 3 or more before "
                "concluding anything.[/]"
            )
        else:
            console.print(f"Largest within-config spread: {within * 100:.1f} pts.")
            if spread <= within:
                console.print(
                    "[yellow]The gap between configurations does not exceed the "
                    "noise within one — this does not distinguish them. Raise "
                    "--repeat further before drawing a conclusion.[/]"
                )
    for r in results:
        if r.skipped:
            console.print(f"[dim]{r.name}: {r.skipped}[/]")


@app.command("stats")
def stats_cmd(namespace: str = typer.Argument(...)) -> None:
    """Show what is indexed in a namespace."""
    with db.connect() as conn:
        stats = db.namespace_stats(conn, namespace)
    console.print(f"{stats['documents']} documents, {stats['chunks']} chunks.")


def _print_spread(runs: list) -> None:
    """Report each metric as mean and range across runs, never as one number."""
    table = Table(title="Across runs", title_style="dim")
    for column in ("run", "claims", "faithfulness", "coverage"):
        table.add_column(column)

    for i, (_, summary) in enumerate(runs, 1):
        table.add_row(
            str(i),
            str(summary["claims"]),
            f"{summary['faithfulness']:.1%}" if summary["faithfulness"] else "—",
            f"{summary['coverage']:.1%}" if summary["coverage"] else "—",
        )
    console.print(table)

    for label, key in (("faithfulness", "faithfulness"), ("coverage", "coverage")):
        values = [s[key] for _, s in runs if s[key] is not None]
        if not values:
            continue
        mean = sum(values) / len(values)
        spread = max(values) - min(values)
        console.print(
            f"[bold]{label}[/] {mean:.1%} "
            # spread is a fraction; percentage points need the x100.
            f"(range {min(values):.1%}–{max(values):.1%}, spread {spread * 100:.1f} pts)"
        )


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
