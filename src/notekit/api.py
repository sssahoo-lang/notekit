"""HTTP API. Runs locally; the same app is what gets deployed later.

Course generation streams over Server-Sent Events so the browser can render
module one while the rest are still being written. Everything else is a plain
JSON endpoint.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import calibration, courses, db, explain, llm, retrieval, style, upload
from .identity import normalize
from .models import Syllabus
from .pipeline import arun_course_events, plan_syllabus


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Existing Docker volumes won't re-run schema.sql; create additive tables here.
    with db.connect() as conn:
        courses.ensure_table(conn)
        conn.commit()
    yield


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


async def _course_events_saving(request: CourseRequest) -> AsyncIterator[dict]:
    """Stream generation, then persist the finished course under the user id."""
    user_id = (request.user or "").strip()
    profile = (
        style.load(normalize(user_id)) if user_id and request.use_style else None
    )

    llm.reset_usage()

    summary = ""
    namespace = request.namespace or ""
    module_titles: list[str] = []
    modules: dict[int, dict] = {}

    async for event in arun_course_events(
        request.goal,
        limit=request.limit,
        skip_ingest=request.skip_ingest,
        with_quiz=request.with_quiz,
        namespace=request.namespace,
        style=profile,
    ):
        etype = event.get("type")
        if etype == "syllabus":
            summary = event.get("summary") or ""
            namespace = event.get("namespace") or namespace
            module_titles = list(event.get("modules") or [])
        elif etype == "module":
            index = int(event["index"])
            notes = event["notes"]
            title = notes.get("module_title") or (
                module_titles[index] if index < len(module_titles) else f"Module {index + 1}"
            )
            modules[index] = {
                "index": index,
                "title": title,
                "notes": notes,
                "error": None,
            }
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

        yield event

        if etype == "done":
            ordered = [modules[i] for i in sorted(modules)]
            # Always persist — even refused modules — so history is complete and
            # the user is not billed again to rediscover the refusal.
            course_id = courses.save(
                user_id=user_id or "anonymous",
                goal=request.goal,
                summary=summary,
                namespace=namespace,
                module_titles=module_titles,
                modules=ordered,
                estimated_cost_usd=event.get("estimated_cost_usd"),
                with_quiz=request.with_quiz,
                used_style=bool(profile),
            )
            yield {"type": "saved", "id": course_id}


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
