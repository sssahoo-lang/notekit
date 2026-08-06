"""HTTP API. Runs locally; the same app is what gets deployed later.

Course generation streams over Server-Sent Events so the browser can render
module one while the rest are still being written. Generation continues in the
background if the client disconnects; an explicit cancel stops it. Everything
else is a plain JSON endpoint.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import calibration, courses, db, explain, llm, retrieval, style, upload
from .identity import normalize
from .models import Module, Syllabus
from .pipeline import arun_course_events, plan_syllabus


@dataclass
class _CourseJob:
    course_id: int
    cancel: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task | None = None
    subscribers: list[asyncio.Queue] = field(default_factory=list)
    # Recent events so a late subscriber (reopen while generating) can catch up.
    history: list[dict] = field(default_factory=list)

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        for event in self.history:
            q.put_nowait(event)
        self.subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        try:
            self.subscribers.remove(q)
        except ValueError:
            pass

    async def publish(self, event: dict) -> None:
        self.history.append(event)
        # Bound memory: keep syllabus + terminal + last N module events.
        if len(self.history) > 400:
            self.history = self.history[-200:]
        for q in list(self.subscribers):
            await q.put(event)


_jobs: dict[int, _CourseJob] = {}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Existing Docker volumes won't re-run schema.sql; create additive tables here.
    with db.connect() as conn:
        courses.ensure_table(conn)
        conn.commit()
    yield
    for job in list(_jobs.values()):
        job.cancel.set()
        if job.task and not job.task.done():
            job.task.cancel()


app = FastAPI(title="NoteKit", version="0.1.0", lifespan=lifespan)

# The Next.js dev server runs on 3000. Deployment will need the real origin
# added here rather than a wildcard.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class CourseRequest(BaseModel):
    goal: str
    namespace: str | None = None
    user: str | None = None
    use_style: bool = False
    limit: int = 10
    skip_ingest: bool = False
    with_quiz: bool = False


class ProgressRequest(BaseModel):
    modules_read: list[int] = []
    bookmark: dict | None = None


class ExplainRequest(BaseModel):
    course_id: int
    module_index: int
    highlighted: str
    question: str | None = None
    user: str | None = None


class StyleLearnRequest(BaseModel):
    user: str
    sample: str


class ClaimRequest(BaseModel):
    """Move courses from orphaned browser ids onto the current identity."""

    user: str
    aliases: list[str] = []


def _module_done(entry: dict | None) -> bool:
    """True when a stored module slot has a terminal result."""
    if not entry:
        return False
    if entry.get("error"):
        return True
    notes = entry.get("notes")
    if not notes:
        return False
    if notes.get("refused"):
        return True
    return bool(str(notes.get("body") or "").strip())


def _missing_indices(course: dict) -> set[int]:
    titles = course.get("module_titles") or []
    by_index = {int(m["index"]): m for m in (course.get("modules") or []) if "index" in m}
    missing: set[int] = set()
    for i in range(len(titles)):
        if not _module_done(by_index.get(i)):
            missing.add(i)
    return missing


async def _sse(events: AsyncIterator[dict]) -> AsyncIterator[str]:
    """Serialise events as SSE frames.

    Async all the way through: handing StreamingResponse a sync generator makes
    Starlette hop to a worker thread for every single item, which for
    token-level output is thousands of hops per course.

    A failure mid-stream cannot become an HTTP error status — headers are long
    gone — so it is delivered as a terminal error event instead.
    """
    try:
        async for event in events:
            yield f"data: {json.dumps(event, default=str)}\n\n"
    except Exception as exc:  # noqa: BLE001
        yield f"data: {json.dumps({'type': 'error', 'error': str(exc)})}\n\n"


async def _run_job(
    job: _CourseJob,
    *,
    goal: str,
    user_id: str,
    use_style: bool,
    with_quiz: bool,
    limit: int,
    skip_ingest: bool,
    namespace: str | None,
    syllabus: Syllabus | None,
    only_indices: set[int] | None,
    existing_modules: dict[int, dict] | None,
) -> None:
    """Generate modules and persist; independent of any SSE subscriber."""
    profile = (
        style.load(normalize(user_id)) if user_id and use_style else None
    )
    llm.reset_usage()

    summary = ""
    # Distinct from the per-module `title` used inside the loop below.
    course_title = ""
    ns = namespace or ""
    module_titles: list[str] = []
    modules: dict[int, dict] = dict(existing_modules or {})
    syllabus_data: dict | None = syllabus.model_dump() if syllabus else None
    saved_event_sent = False
    terminal = "complete"

    def _ordered() -> list[dict]:
        return [modules[i] for i in sorted(modules)]

    def _flush(*, cost: float | None = None, status: str | None = None) -> None:
        courses.update(
            job.course_id,
            summary=summary or None,
            title=course_title or None,
            namespace=ns or None,
            module_titles=module_titles or None,
            modules=_ordered(),
            estimated_cost_usd=cost,
            generation_status=status,
            syllabus=syllabus_data,
        )

    try:
        async for event in arun_course_events(
            goal,
            limit=limit,
            skip_ingest=skip_ingest,
            with_quiz=with_quiz,
            namespace=namespace,
            style=profile,
            syllabus=syllabus,
            cancel_event=job.cancel,
            only_indices=only_indices,
        ):
            etype = event.get("type")
            if etype == "syllabus":
                summary = event.get("summary") or ""
                course_title = event.get("title") or course_title
                ns = event.get("namespace") or ns
                module_titles = list(event.get("modules") or [])
                syllabus_data = event.get("syllabus") or syllabus_data
                _flush(status="generating")
                await job.publish(event)
                if not saved_event_sent:
                    saved_event_sent = True
                    await job.publish({"type": "saved", "id": job.course_id})
                continue

            if etype == "module":
                index = int(event["index"])
                notes = event["notes"]
                title = notes.get("module_title") or (
                    module_titles[index]
                    if index < len(module_titles)
                    else f"Module {index + 1}"
                )
                modules[index] = {
                    "index": index,
                    "title": title,
                    "notes": notes,
                    "error": None,
                }
                _flush(status="generating")
            elif etype == "module_error":
                index = int(event["index"])
                title = (
                    module_titles[index]
                    if index < len(module_titles)
                    else f"Module {index + 1}"
                )
                modules[index] = {
                    "index": index,
                    "title": title,
                    "notes": None,
                    "error": event.get("error"),
                }
                _flush(status="generating")
            elif etype == "done":
                terminal = "complete"
                _flush(cost=event.get("estimated_cost_usd"), status="complete")
                await job.publish(event)
                await job.publish({"type": "saved", "id": job.course_id})
                continue
            elif etype == "cancelled":
                terminal = "partial"
                _flush(status="partial")
                await job.publish(event)
                await job.publish({"type": "saved", "id": job.course_id})
                continue
            elif etype == "error":
                terminal = "partial"
                _flush(status="partial")
                await job.publish(event)
                continue

            await job.publish(event)
    except Exception as exc:  # noqa: BLE001
        terminal = "partial"
        _flush(status="partial")
        await job.publish({"type": "error", "error": str(exc)})
    finally:
        if job.cancel.is_set() and terminal != "complete":
            _flush(status="partial")
        elif terminal == "complete":
            _flush(status="complete")
        else:
            # Job ended without a clean done (disconnect of job itself, etc.).
            row = courses.get(job.course_id)
            if row and row.get("generation_status") == "generating":
                missing = _missing_indices(row)
                _flush(status="partial" if missing else "complete")
        _jobs.pop(job.course_id, None)


def _start_job(
    course_id: int,
    *,
    goal: str,
    user_id: str,
    use_style: bool,
    with_quiz: bool,
    limit: int,
    skip_ingest: bool,
    namespace: str | None,
    syllabus: Syllabus | None = None,
    only_indices: set[int] | None = None,
    existing_modules: dict[int, dict] | None = None,
) -> _CourseJob:
    existing = _jobs.get(course_id)
    if existing and existing.task and not existing.task.done():
        return existing

    job = _CourseJob(course_id=course_id)
    job.task = asyncio.create_task(
        _run_job(
            job,
            goal=goal,
            user_id=user_id,
            use_style=use_style,
            with_quiz=with_quiz,
            limit=limit,
            skip_ingest=skip_ingest,
            namespace=namespace,
            syllabus=syllabus,
            only_indices=only_indices,
            existing_modules=existing_modules,
        )
    )
    _jobs[course_id] = job
    return job


async def _subscribe_events(job: _CourseJob) -> AsyncIterator[dict]:
    """Yield job events to one SSE client without owning the job lifetime."""
    q = job.subscribe()
    try:
        while True:
            event = await q.get()
            yield event
            if event.get("type") in ("done", "cancelled", "error"):
                # Allow a trailing saved event if it arrives immediately after.
                try:
                    while True:
                        nxt = q.get_nowait()
                        yield nxt
                        if nxt.get("type") in ("done", "cancelled", "error"):
                            continue
                except asyncio.QueueEmpty:
                    pass
                break
    finally:
        job.unsubscribe(q)


async def _course_events_saving(request: CourseRequest) -> AsyncIterator[dict]:
    """Start a background course job and stream its events to this client.

    Closing the SSE connection unsubscribes only — generation keeps going.
    Call POST /api/courses/{id}/cancel to stop explicitly.
    """
    user_id = (request.user or "").strip() or "anonymous"
    # Placeholder row so History has an id before planning finishes.
    course_id = courses.save(
        user_id=user_id,
        goal=request.goal,
        summary="",
        namespace=request.namespace or "",
        module_titles=[],
        modules=[],
        estimated_cost_usd=None,
        with_quiz=request.with_quiz,
        used_style=bool(request.use_style),
        generation_status="generating",
    )
    yield {"type": "saved", "id": course_id}

    job = _start_job(
        course_id,
        goal=request.goal,
        user_id=user_id,
        use_style=request.use_style,
        with_quiz=request.with_quiz,
        limit=request.limit,
        skip_ingest=request.skip_ingest,
        namespace=request.namespace,
    )
    async for event in _subscribe_events(job):
        yield event


async def _resume_events(course_id: int) -> AsyncIterator[dict]:
    course = courses.get(course_id)
    if not course:
        yield {"type": "error", "error": f"course {course_id} not found"}
        return

    missing = _missing_indices(course)
    if not missing:
        courses.set_generation_status(course_id, "complete")
        yield {"type": "done", "estimated_cost_usd": course.get("estimated_cost_usd") or 0, "usage": []}
        yield {"type": "saved", "id": course_id}
        return

    existing_job = _jobs.get(course_id)
    if existing_job and existing_job.task and not existing_job.task.done():
        async for event in _subscribe_events(existing_job):
            yield event
        return

    syllabus_data = course.get("syllabus")
    syllabus = Syllabus.model_validate(syllabus_data) if syllabus_data else None
    if syllabus is None:
        # Older rows: rebuild a minimal syllabus from titles so resume still works.
        titles = course.get("module_titles") or []
        if not titles:
            yield {"type": "error", "error": "This course has no syllabus to resume."}
            return
        syllabus = Syllabus(
            topic_slug=course.get("namespace") or "topic",
            summary=course.get("summary") or "",
            modules=[
                Module(
                    title=t,
                    query=t,
                    learning_goals=[f"Understand {t}"],
                )
                for t in titles
            ],
        )

    courses.set_generation_status(course_id, "generating")
    by_index = {
        int(m["index"]): m for m in (course.get("modules") or []) if "index" in m
    }

    job = _start_job(
        course_id,
        goal=course["goal"],
        user_id=course.get("user_id") or "anonymous",
        use_style=bool(course.get("used_style")),
        with_quiz=bool(course.get("with_quiz")),
        limit=10,
        skip_ingest=True,
        namespace=course.get("namespace") or None,
        syllabus=syllabus,
        only_indices=missing,
        existing_modules=by_index,
    )
    async for event in _subscribe_events(job):
        yield event


@app.get("/api/health")
def health() -> dict:
    try:
        with db.connect() as conn:
            conn.execute("SELECT 1")
        return {"status": "ok", "database": "connected"}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"database unavailable: {exc}") from exc


@app.get("/api/namespaces")
def namespaces() -> list[dict]:
    """Every namespace with indexed content, for populating a picker."""
    with db.connect() as conn:
        # Chunks are counted in a subquery, not a join: joining documents to
        # chunks on namespace multiplies the two counts together.
        rows = conn.execute(
            """
            SELECT d.namespace,
                   count(*) AS documents,
                   (SELECT count(*) FROM chunks c
                     WHERE c.namespace = d.namespace) AS chunks
            FROM documents d
            GROUP BY d.namespace
            ORDER BY d.namespace
            """
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/courses")
def list_courses(user: str = "anonymous") -> list[dict]:
    """Saved courses for a user, most recently opened first."""
    return courses.list_for_user(normalize(user))


@app.post("/api/courses/claim")
def claim_courses(request: ClaimRequest) -> dict:
    """Reassign courses from old browser identities to the current one."""
    moved = courses.claim(request.aliases, request.user)
    return {
        "moved": moved,
        "user": normalize(request.user),
        "courses": courses.list_for_user(request.user),
    }


@app.get("/api/courses/{course_id}")
def get_course(course_id: int) -> dict:
    row = courses.get(course_id)
    if not row:
        raise HTTPException(404, f"course {course_id} not found")
    # Reopening counts as activity, so "continue studying" tracks what you are
    # actually reading rather than what you generated most recently.
    courses.touch(course_id)
    return row


@app.patch("/api/courses/{course_id}/progress")
def set_progress(course_id: int, request: ProgressRequest) -> dict:
    """Record which modules have been read and where the bookmark sits."""
    updated = courses.set_progress(
        course_id,
        {"modules_read": sorted(set(request.modules_read)), "bookmark": request.bookmark},
    )
    if not updated:
        raise HTTPException(404, f"course {course_id} not found")
    return updated


@app.post("/api/courses/{course_id}/cancel")
async def cancel_course(course_id: int) -> dict:
    """Stop background generation; keep whatever modules already finished."""
    job = _jobs.get(course_id)
    if job:
        job.cancel.set()
        return {"id": course_id, "generation_status": "partial", "cancelling": True}
    row = courses.get(course_id)
    if not row:
        raise HTTPException(404, f"course {course_id} not found")
    if row.get("generation_status") == "generating":
        courses.set_generation_status(course_id, "partial")
        row = courses.get(course_id) or row
    return {
        "id": course_id,
        "generation_status": row.get("generation_status"),
        "cancelling": False,
    }


@app.post("/api/courses/{course_id}/resume")
def resume_course(course_id: int) -> StreamingResponse:
    """Regenerate missing modules for a partial course."""
    row = courses.get(course_id)
    if not row:
        raise HTTPException(404, f"course {course_id} not found")
    return StreamingResponse(
        _sse(_resume_events(course_id)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/explain")
def explain_selection(request: ExplainRequest) -> dict:
    """Explain a highlighted span using that module's own source passages."""
    course = courses.get(request.course_id)
    if not course:
        raise HTTPException(404, f"course {request.course_id} not found")

    passages, found = explain.passages_for_module(course, request.module_index)
    if not found:
        raise HTTPException(
            422,
            "That module has no stored source passages, so there is nothing to "
            "explain it from.",
        )

    llm.reset_usage()
    try:
        answer = explain.explain(
            passages=passages,
            highlighted=request.highlighted,
            question=request.question,
            style=style.load(normalize(request.user)) if request.user else None,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    _, cost = llm.usage_report()
    return {"answer": answer, "estimated_cost_usd": round(cost, 4)}


@app.delete("/api/courses/{course_id}")
def delete_course(course_id: int, user: str | None = None) -> dict:
    job = _jobs.get(course_id)
    if job:
        job.cancel.set()
    ok = courses.delete(course_id, user_id=user)
    if not ok:
        raise HTTPException(404, f"course {course_id} not found")
    return {"deleted": course_id}


@app.post("/api/course")
def course(request: CourseRequest) -> StreamingResponse:
    """Stream a course as its modules complete; persist when finished."""
    return StreamingResponse(
        _sse(_course_events_saving(request)),
        media_type="text/event-stream",
        # Without this, a proxy may buffer the whole stream and defeat the point.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/plan")
def plan(goal: str = Form(...)) -> Syllabus:
    llm.reset_usage()
    return plan_syllabus(goal)


@app.get("/api/search")
def search(q: str, namespace: str) -> list[dict]:
    chunks = retrieval.retrieve(query=q, namespace=namespace)
    return [c.model_dump() for c in chunks]


@app.post("/api/upload")
async def upload_files(
    user: str = Form(...),
    topic: str = Form("notes"),
    files: list[UploadFile] = File(...),
) -> dict:
    """Index uploaded files into the caller's namespace."""
    try:
        namespace = upload.user_namespace(user, topic)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    # Written to a temp directory because the parsers work on paths, and it is
    # cleaned up whether or not indexing succeeds.
    with tempfile.TemporaryDirectory() as tmp:
        paths = []
        for upload_file in files:
            if not upload_file.filename:
                continue
            target = Path(tmp) / Path(upload_file.filename).name
            target.write_bytes(await upload_file.read())
            paths.append(str(target))

        if not paths:
            raise HTTPException(400, "no files received")
        summary = upload.ingest_files(paths, namespace=namespace)

    return {"namespace": namespace, **summary}


@app.get("/api/style/{user}")
def get_style(user: str) -> dict:
    profile = style.load(normalize(user))
    if not profile:
        raise HTTPException(404, f"no style profile for {user}")
    return profile.model_dump()


@app.post("/api/style/learn")
def learn_style(request: StyleLearnRequest) -> dict:
    llm.reset_usage()
    try:
        profile = style.learn(request.sample)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    style.save(normalize(request.user), profile, len(request.sample))
    return profile.model_dump()


@app.post("/api/calibrate")
def calibrate(evalset_path: str = Form(...)) -> dict:
    try:
        calset = calibration.CalibrationSet.load(evalset_path)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    return calibration.calibrate(calset).model_dump()
