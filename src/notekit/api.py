"""HTTP API. Runs locally; the same app is what gets deployed later.

Course generation streams over Server-Sent Events so the browser can render
module one while the rest are still being written. Generation continues in the
background if the client disconnects; an explicit cancel stops it. Everything
else is a plain JSON endpoint.
"""

from __future__ import annotations

import asyncio
import json
import os
import httpx
import tempfile
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from . import (
    accounts,
    mail,
    auth,
    calibration,
    config,
    courses,
    db,
    evaluation,
    explain,
    llm,
    retrieval,
    sources,
    style,
    suggest,
    upload,
)
from .identity import normalize
from .models import Module, Syllabus
from .pipeline import arun_course_events, plan_syllabus
from .preferences import NotePreferences


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
    from . import config as _config

    _config.load_runtime_settings()
    with db.connect() as conn:
        courses.ensure_table(conn)
        conn.commit()
    # In-memory generation jobs die with the process; don't leave History saying
    # "Generating" for courses that can no longer be writing.
    purged = courses.purge_deleted()
    if purged:
        print(f"purged {purged} course(s) deleted more than a week ago")
    abandoned = courses.abandon_stale_generating()
    if abandoned:
        print(f"Reconciled {abandoned} abandoned generating course(s) → partial")
    yield
    for job in list(_jobs.values()):
        job.cancel.set()
        if job.task and not job.task.done():
            job.task.cancel()


app = FastAPI(title="NoteKit", version="0.1.0", lifespan=lifespan)


class PasswordRequest(BaseModel):
    password: str


@app.middleware("http")
async def site_password_gate(request, call_next):
    """Refuse everything except the open paths until the password is presented.

    Only active when SITE_PASSWORD is set, so local development is untouched.
    """
    if not auth.enabled() or request.method == "OPTIONS":
        return await call_next(request)

    path = request.url.path
    if path in auth.OPEN_PATHS:
        return await call_next(request)
    if not path.startswith("/api/") and path not in auth.DOCS_PATHS:
        return await call_next(request)

    if not auth.check_token(request.headers.get(auth.HEADER)):
        return JSONResponse(
            {"detail": "This instance is password protected."},
            status_code=401,
            # Marks this as the instance gate rather than a sign-in failure.
            # Both are 401s, and without something to tell them apart the
            # client showed "enter the site password" to someone who had
            # simply mistyped their own.
            headers={auth.GATE_HEADER: "1"},
        )
    return await call_next(request)


# --- Ownership, throttling, budget -------------------------------------------
#
# Reader ids are unauthenticated bearer strings: knowing one is being that
# reader. That is the trust model the README states, and the routes below now
# hold to it. Course ids are sequential integers, so without these checks a
# course was reachable by anyone who could count.

_rate_windows: dict[tuple[str, str], list[float]] = {}


def _app_origin() -> str:
    """Where the web app lives, for links sent by mail.

    The API and the app are different origins, and a reset link has to point
    at the app. ALLOWED_ORIGINS already names it.
    """
    return os.environ.get("APP_ORIGIN", "").strip() or (
        _origins[0] if _origins else "http://localhost:3000"
    )


def _signed_in(request: Request) -> dict | None:
    """The account behind this request's session cookie, if there is one."""
    return accounts.session_user(request.cookies.get(accounts.SESSION_COOKIE))


def _caller(request: Request, user: str | None = None) -> str:
    """The storage key this request acts as.

    A session wins over anything the client says it is. Without one the old
    browser id still works, so the app is usable without an account and a
    reader who had courses before accounts existed does not lose them.
    """
    account = _signed_in(request)
    if account:
        return accounts.account_key(account["id"])
    if not user:
        raise HTTPException(422, "Sign in, or send a reader id.")
    return normalize(user)


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        accounts.SESSION_COOKIE,
        token,
        max_age=accounts.SESSION_DAYS * 24 * 3600,
        httponly=True,
        samesite="lax",
        secure=_COOKIE_SECURE,
        path="/",
    )


def _account_payload(account: dict, key: str) -> dict:
    return {
        "id": account["id"],
        "email": account["email"],
        "display_name": account["display_name"],
        "key": key,
    }


def _owned(course_id: int, user: str) -> dict:
    """Load a course the caller owns, or 404.

    404 rather than 403 on a mismatch. Confirming that an id exists but belongs
    to someone else is itself a small leak, and sequential ids make it a cheap
    one to harvest.
    """
    row = courses.get(course_id)
    if not row or row.get("user_id") != normalize(user):
        raise HTTPException(404, f"course {course_id} not found")
    return row


def _throttle(bucket: str, user: str) -> None:
    """Sliding-window rate limit per reader, in memory, per process."""
    limit, window = config.RATE_LIMITS[bucket]
    key = (bucket, normalize(user))
    now = time.monotonic()
    recent = [t for t in _rate_windows.get(key, []) if now - t < window]
    if len(recent) >= limit:
        raise HTTPException(
            429,
            f"Too many {bucket} requests: the limit is {limit} per "
            f"{window // 60} minutes.",
        )
    recent.append(now)
    _rate_windows[key] = recent


def _check_budget(user: str) -> None:
    """Refuse to start paid work once a reader has spent the day's allowance."""
    spent = courses.spent_today(user)
    if spent >= config.DAILY_BUDGET_USD:
        raise HTTPException(
            429,
            f"Daily budget reached: ${spent:.2f} of ${config.DAILY_BUDGET_USD:.2f} "
            "in the last 24 hours. Try again later.",
        )


def _ensure_namespace_access(namespace: str, user: str) -> None:
    """Uploaded material is private to the reader who uploaded it."""
    if namespace.startswith("user-") and not namespace.startswith(
        f"user-{normalize(user)}-"
    ):
        raise HTTPException(404, f"namespace {namespace!r} not found")


@app.post("/api/auth")
def site_login(request: PasswordRequest) -> dict:
    """Exchange the shared password for the access token."""
    if not auth.enabled():
        return {"token": "", "required": False}
    if not auth.check_password(request.password):
        raise HTTPException(401, "Incorrect password.")
    return {"token": auth.token_for(request.password), "required": True}


@app.get("/api/auth")
def site_auth_required() -> dict:
    """Whether this instance is gated, so the UI can decide to show a prompt."""
    return {"required": auth.enabled()}

# The Next.js dev server runs on 3000. Deployment will need the real origin
# added here rather than a wildcard.
# Deployment sets ALLOWED_ORIGINS to the real frontend URL; localhost stays so
# a local UI can talk to a deployed API while debugging.
_origins = [
    o.strip()
    for o in os.environ.get(
        "ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
    ).split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    # The session is a cookie, so the browser only sends it when asked to, and
    # only to the origins named above. A wildcard origin is not allowed with
    # credentials, which is the rule doing the work here.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Response headers are hidden from page scripts unless named here.
    expose_headers=[auth.GATE_HEADER],
)

# Cookies are marked Secure off a real deployment; over plain http on localhost
# a Secure cookie would simply never be sent.
_COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "").strip().lower() in {"1", "true", "yes"}


class CourseRequest(BaseModel):
    goal: str
    namespace: str | None = None
    user: str | None = None
    use_style: bool = False
    limit: int = 10
    skip_ingest: bool = False
    with_quiz: bool = False
    preferences: NotePreferences | None = None
    # A syllabus the reader has already reviewed. Planning is skipped and the
    # course is written to exactly this outline.
    syllabus: Syllabus | None = None
    # Documents the reader struck during review. Retrieval for this course
    # ignores them; the shared corpus is untouched.
    excluded_documents: list[int] = []


class RegisterRequest(BaseModel):
    email: str
    password: str
    display_name: str = ""
    # Browser ids used before signing up. Their courses move to the account, so
    # signing up does not look like losing everything.
    claim: list[str] = []


class LoginRequest(BaseModel):
    email: str
    password: str
    claim: list[str] = []


class DisplayNameRequest(BaseModel):
    display_name: str


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


class ForgotRequest(BaseModel):
    email: str


class ResetRequest(BaseModel):
    token: str
    new_password: str


class SourcesRequest(BaseModel):
    syllabus: Syllabus
    user: str | None = None
    namespace: str | None = None
    limit: int = 10


class AddUrlRequest(BaseModel):
    url: str
    namespace: str
    user: str | None = None


class PlanRequest(BaseModel):
    goal: str
    user: str | None = None
    preferences: NotePreferences | None = None


class ProgressRequest(BaseModel):
    user: str
    modules_read: list[int] = []
    bookmark: dict | None = None


class ExplainRequest(BaseModel):
    course_id: int
    module_index: int
    highlighted: str
    question: str | None = None
    user: str


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

    A failure mid-stream cannot become an HTTP error status (headers are long
    gone), so it is delivered as a terminal error event instead.
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
    preferences: NotePreferences | None = None,
    excluded_documents: list[int] | None = None,
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

    # Teaching judges run beside generation, one task per finished section,
    # so a section reaches the reader the moment it is written rather than
    # after a judge call. They are gathered before the course is marked
    # complete so the last score is stored, and a judge that fails costs only
    # its score: the section is already saved by the time it starts.
    judge_tasks: list[asyncio.Task] = []

    async def _judge_section(index: int, body: str, goals: list[str]) -> None:
        level = preferences.level if preferences else None
        try:
            checks = await asyncio.to_thread(evaluation.judge_teaching, body, goals, level)
        except Exception as exc:  # noqa: BLE001
            print(f"  ! teaching judge failed for section {index + 1}: {exc}")
            return
        summary_ = evaluation.teaching_summary(checks)
        if index in modules:
            modules[index]["teaching"] = summary_
            _flush()
        await job.publish({"type": "teaching", "index": index, **summary_})

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
            prefs=preferences,
            exclude=excluded_documents or None,
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
                    "teaching": None,
                }
                _flush(status="generating")
                body = (notes or {}).get("body") or ""
                syl_modules = (syllabus_data or {}).get("modules") or []
                goals = (
                    syl_modules[index].get("learning_goals") or []
                    if index < len(syl_modules)
                    else []
                )
                if config.TEACHING_AT_GENERATION and body and goals and not notes.get("refused"):
                    judge_tasks.append(asyncio.create_task(_judge_section(index, body, goals)))
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
                if judge_tasks:
                    await asyncio.gather(*judge_tasks, return_exceptions=True)
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
    preferences: NotePreferences | None = None,
    excluded_documents: list[int] | None = None,
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
            preferences=preferences,
            excluded_documents=excluded_documents,
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

    Closing the SSE connection unsubscribes only; generation keeps going.
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
        preferences=(
            request.preferences.model_dump(exclude_none=True)
            if request.preferences and not request.preferences.is_empty()
            else None
        ),
        excluded_documents=request.excluded_documents or None,
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
        preferences=request.preferences,
        syllabus=request.syllabus,
        excluded_documents=request.excluded_documents,
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
        preferences=(
            NotePreferences(**course["preferences"])
            if course.get("preferences")
            else None
        ),
        excluded_documents=course.get("excluded_documents") or None,
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
def namespaces(request: Request, user: str = "anonymous") -> list[dict]:
    """Namespaces the caller may build from: shared topics and their own uploads.

    Listing every namespace handed out the reader id of everyone who had ever
    uploaded, which is the one string the whole trust model rests on.
    """
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
    mine = f"user-{_caller(request, user)}-"
    return [
        dict(r)
        for r in rows
        if not r["namespace"].startswith("user-") or r["namespace"].startswith(mine)
    ]


@app.get("/api/courses")
def list_courses(request: Request, user: str = "anonymous") -> list[dict]:
    """Saved courses for the caller, most recently opened first."""
    return courses.list_for_user(_caller(request, user))


@app.post("/api/courses/claim")
def claim_courses(body: ClaimRequest, request: Request) -> dict:
    """Reassign courses from old browser identities onto the caller.

    The destination is the caller, never the body: otherwise anyone could
    claim another reader's courses by naming them here.
    """
    caller = _caller(request, body.user)
    moved = courses.claim(body.aliases, caller)
    return {
        "moved": moved,
        "user": caller,
        "courses": courses.list_for_user(caller),
    }


@app.get("/api/courses/{course_id}")
def get_course(course_id: int, request: Request, user: str | None = None) -> dict:
    row = _owned(course_id, _caller(request, user))
    # Reopening counts as activity, so "continue studying" tracks what you are
    # actually reading rather than what you generated most recently.
    courses.touch(course_id)
    return row


@app.patch("/api/courses/{course_id}/progress")
def set_progress(
    course_id: int, body: ProgressRequest, request: Request
) -> dict:
    """Record which modules have been read and where the bookmark sits."""
    _owned(course_id, _caller(request, body.user))
    updated = courses.set_progress(
        course_id,
        {"modules_read": sorted(set(body.modules_read)), "bookmark": body.bookmark},
    )
    if not updated:
        raise HTTPException(404, f"course {course_id} not found")
    return updated


@app.post("/api/courses/{course_id}/cancel")
async def cancel_course(
    course_id: int, request: Request, user: str | None = None
) -> dict:
    """Stop background generation; keep whatever modules already finished."""
    _owned(course_id, _caller(request, user))
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
def resume_course(
    course_id: int, request: Request, user: str | None = None
) -> StreamingResponse:
    """Regenerate missing modules for a partial course."""
    caller = _caller(request, user)
    _owned(course_id, caller)
    _throttle("course", caller)
    _check_budget(caller)
    return StreamingResponse(
        _sse(_resume_events(course_id)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/explain")
def explain_selection(body: ExplainRequest, request: Request) -> dict:
    """Explain a highlighted span using that module's own source passages."""
    caller = _caller(request, body.user)
    course = _owned(body.course_id, caller)
    _throttle("explain", caller)

    passages, found = explain.passages_for_module(course, body.module_index)
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
            highlighted=body.highlighted,
            question=body.question,
            style=style.load(caller),
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    _, cost = llm.usage_report()
    return {"answer": answer, "estimated_cost_usd": round(cost, 4)}


@app.post("/api/courses/{course_id}/restore")
def restore_course(
    course_id: int, request: Request, user: str | None = None
) -> dict:
    """Undo a delete, while the row is still there to undo."""
    if not courses.restore(course_id, user_id=_caller(request, user)):
        raise HTTPException(404, f"course {course_id} cannot be restored")
    return {"restored": course_id}


@app.delete("/api/courses/{course_id}")
def delete_course(course_id: int, request: Request, user: str | None = None) -> dict:
    caller = _caller(request, user)
    _owned(course_id, caller)
    job = _jobs.get(course_id)
    if job:
        job.cancel.set()
    ok = courses.delete(course_id, user_id=caller)
    if not ok:
        raise HTTPException(404, f"course {course_id} not found")
    return {"deleted": course_id}


@app.post("/api/course")
def course(body: CourseRequest, request: Request) -> StreamingResponse:
    """Stream a course as its modules complete; persist when finished."""
    caller = _caller(request, body.user)
    # The course is saved under the caller, so a signed-in reader's courses
    # follow the account rather than the browser that asked for them.
    body = body.model_copy(update={"user": caller})
    _throttle("course", caller)
    _check_budget(caller)
    if body.syllabus is not None and not 1 <= len(body.syllabus.modules) <= 8:
        raise HTTPException(422, "A course needs between one and eight sections.")
    return StreamingResponse(
        _sse(_course_events_saving(body)),
        media_type="text/event-stream",
        # Without this, a proxy may buffer the whole stream and defeat the point.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/plan")
def plan(request: PlanRequest) -> Syllabus:
    """Plan only, so the reader can revise the outline before paying to write it.

    Planning is one Haiku call, well under a cent. Generation is a hundred
    times that. Until now the first time a reader saw the syllabus was after
    the expensive part, which is the wrong way round.
    """
    caller = request.user or "anonymous"
    _throttle("plan", caller)
    llm.reset_usage()
    level = request.preferences.level if request.preferences else None
    return plan_syllabus(request.goal, level=level)


@app.post("/api/sources")
async def gather_sources(request: SourcesRequest) -> dict:
    """Fetch the corpus an outline needs, and return what it holds.

    Runs in a thread because a new subject means minutes of downloading and
    embedding, none of which should sit on the event loop.
    """
    caller = request.user or "anonymous"
    _throttle("sources", caller)
    if request.namespace:
        _ensure_namespace_access(request.namespace, caller)
    return await asyncio.to_thread(
        sources.gather,
        request.syllabus,
        namespace=request.namespace,
        limit=request.limit,
    )


@app.post("/api/sources/url")
async def add_source_url(request: AddUrlRequest) -> dict:
    """Index one page or PDF the reader chose, into the course's corpus."""
    caller = request.user or "anonymous"
    _throttle("sources", caller)
    _ensure_namespace_access(request.namespace, caller)
    try:
        return await asyncio.to_thread(sources.add_url, request.url, namespace=request.namespace)
    except sources.UnsafeUrl as exc:
        raise HTTPException(422, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Could not fetch that link: {exc}") from exc


@app.get("/api/suggest")
def suggest_instant(request: Request, q: str, user: str = "anonymous") -> dict:
    """Own courses and indexed subjects matching the text so far. No model call."""
    return suggest.instant(q, _caller(request, user))


@app.get("/api/suggest/related")
def suggest_related(request: Request, q: str, user: str = "anonymous") -> dict:
    """Goals a learner typing this might mean. One small model call, cached."""
    _throttle("suggest", _caller(request, user))
    return {"goals": suggest.related(q)}


@app.post("/api/register")
def register_account(request: RegisterRequest, response: Response) -> dict:
    """Create an account and sign in, carrying this browser's courses across."""
    try:
        account = accounts.register(
            request.email, request.password, request.display_name
        )
    except accounts.AccountError as exc:
        raise HTTPException(422, str(exc)) from exc
    key = accounts.account_key(account["id"])
    if request.claim:
        courses.claim(request.claim, key)
    _set_session_cookie(response, accounts.start_session(account["id"]))
    return _account_payload(account, key)


@app.post("/api/login")
def login(request: LoginRequest, response: Response) -> dict:
    """Sign in. The reply never says which half of the pair was wrong."""
    _throttle("login", request.email.strip().lower() or "anonymous")
    account = accounts.authenticate(request.email, request.password)
    if account is None:
        raise HTTPException(401, "That email and password do not match.")
    key = accounts.account_key(account["id"])
    if request.claim:
        courses.claim(request.claim, key)
    _set_session_cookie(response, accounts.start_session(account["id"]))
    return _account_payload(account, key)


@app.post("/api/logout")
def logout(request: Request, response: Response) -> dict:
    accounts.end_session(request.cookies.get(accounts.SESSION_COOKIE))
    response.delete_cookie(accounts.SESSION_COOKIE, path="/")
    return {"signed_out": True}


@app.get("/api/me")
def me(request: Request) -> dict:
    """Who this request is. Always answers, so the UI needs no error path."""
    account = _signed_in(request)
    if account is None:
        return {"signed_in": False}
    return {
        "signed_in": True,
        **_account_payload(account, accounts.account_key(account["id"])),
    }


@app.patch("/api/me")
def update_me(body: DisplayNameRequest, request: Request) -> dict:
    account = _signed_in(request)
    if account is None:
        raise HTTPException(401, "Sign in first.")
    accounts.set_display_name(account["id"], body.display_name)
    return {"display_name": body.display_name.strip()}


@app.post("/api/me/password")
def change_password(body: PasswordChangeRequest, request: Request) -> dict:
    account = _signed_in(request)
    if account is None:
        raise HTTPException(401, "Sign in first.")
    _throttle("login", account["email"])
    try:
        accounts.change_password(
            account["id"], body.current_password, body.new_password
        )
    except accounts.AccountError as exc:
        raise HTTPException(422, str(exc)) from exc
    # Every session was dropped, including this one.
    return {"changed": True, "signed_out_everywhere": True}


@app.post("/api/password/forgot")
def forgot_password(body: ForgotRequest) -> dict:
    """Start a reset. Answers the same way whether or not the address exists.

    Anything else turns this into a way to ask which addresses have accounts.
    """
    _throttle("reset", body.email.strip().lower() or "anonymous")
    issued = accounts.begin_reset(body.email)
    if issued:
        token, address = issued
        link = f"{_app_origin()}/reset?token={token}"
        mail.send(
            address,
            "Reset your NoteKit password",
            "Someone asked to reset the NoteKit password for this address.\n\n"
            f"{link}\n\n"
            f"The link works once and expires in {accounts.RESET_MINUTES} minutes. "
            "If this was not you, nothing has changed and you can ignore this.",
        )
    return {
        "sent": True,
        "detail": (
            "If that address has an account, a reset link is on its way. "
            "The link expires in an hour."
        ),
    }


@app.post("/api/password/reset")
def reset_password(body: ResetRequest) -> dict:
    """Spend a reset link. Every session for that account ends."""
    _throttle("reset", "reset-token")
    try:
        ok = accounts.complete_reset(body.token, body.new_password)
    except accounts.AccountError as exc:
        raise HTTPException(422, str(exc)) from exc
    if not ok:
        raise HTTPException(
            422,
            "That link has expired or been used already. Ask for a new one.",
        )
    return {"reset": True}


@app.get("/api/search")
def search(
    request: Request, q: str, namespace: str, user: str = "anonymous"
) -> list[dict]:
    _ensure_namespace_access(namespace, _caller(request, user))
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
    if len(files) > config.MAX_UPLOAD_FILES:
        raise HTTPException(413, f"At most {config.MAX_UPLOAD_FILES} files per upload.")
    _throttle("upload", user)

    with tempfile.TemporaryDirectory() as tmp:
        paths = []
        for upload_file in files:
            if not upload_file.filename:
                continue
            target = Path(tmp) / Path(upload_file.filename).name
            # Read in pieces and stop at the cap, rather than reading the whole
            # body and then measuring it: by then the memory is already spent.
            written = 0
            with target.open("wb") as out:
                while chunk := await upload_file.read(1024 * 1024):
                    written += len(chunk)
                    if written > config.MAX_UPLOAD_BYTES:
                        raise HTTPException(
                            413,
                            f"{upload_file.filename} exceeds the "
                            f"{config.MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.",
                        )
                    out.write(chunk)
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
def calibrate(
    evalset_path: str = Form(...),
    apply: bool = Form(False),
) -> dict:
    """Measure the refusal threshold; pass apply=true to persist it for runtime."""
    try:
        calset = calibration.CalibrationSet.load(evalset_path)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    if apply:
        # Persisting a threshold changes every reader's refusal behaviour.
        # That is an operator decision, taken at the CLI, not something any
        # holder of the site password should be able to do over HTTP.
        raise HTTPException(403, "apply is only available from the CLI.")
    return calibration.calibrate(calset, apply=False).model_dump()
