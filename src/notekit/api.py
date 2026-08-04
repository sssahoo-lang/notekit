"""HTTP API. Runs locally; the same app is what gets deployed later.

Course generation streams over Server-Sent Events so the browser can render
module one while the rest are still being written. Everything else is a plain
JSON endpoint.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Iterator
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import calibration, db, llm, retrieval, style, upload
from .models import Syllabus
from .pipeline import plan_syllabus, run_course_events

app = FastAPI(title="NoteKit", version="0.1.0")

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
    limit: int = 10
    skip_ingest: bool = False
    with_quiz: bool = False


class StyleLearnRequest(BaseModel):
    user: str
    sample: str


def _sse(events: Iterator[dict]) -> Iterator[str]:
    """Serialise events as SSE frames.

    A failure mid-stream cannot become an HTTP error status — headers are long
    gone — so it is delivered as a terminal error event instead.
    """
    try:
        for event in events:
            yield f"data: {json.dumps(event, default=str)}\n\n"
    except Exception as exc:  # noqa: BLE001
        yield f"data: {json.dumps({'type': 'error', 'error': str(exc)})}\n\n"


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


@app.post("/api/course")
def course(request: CourseRequest) -> StreamingResponse:
    """Stream a course as its modules complete."""
    profile = style.load(request.user) if request.user else None
    llm.reset_usage()

    events = run_course_events(
        request.goal,
        limit=request.limit,
        skip_ingest=request.skip_ingest,
        with_quiz=request.with_quiz,
        namespace=request.namespace,
        style=profile,
    )
    return StreamingResponse(
        _sse(events),
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
    profile = style.load(user)
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
    style.save(request.user, profile, len(request.sample))
    return profile.model_dump()


@app.post("/api/calibrate")
def calibrate(evalset_path: str = Form(...)) -> dict:
    try:
        calset = calibration.CalibrationSet.load(evalset_path)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    return calibration.calibrate(calset).model_dump()
