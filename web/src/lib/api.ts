import type {
  CourseEvent,
  CourseProgress,
  CourseRequest,
  NamespaceInfo,
  NotePreferences,
  SavedCourse,
  SavedCourseSummary,
  SourceDocument,
  StyleProfile,
  Syllabus,
  UploadResult,
} from "./types";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") || "http://localhost:8000";

export function apiBase(): string {
  return API_BASE;
}

async function readError(res: Response): Promise<string> {
  try {
    const data = await res.json();
    if (typeof data?.detail === "string") return data.detail;
    return JSON.stringify(data);
  } catch {
    return res.statusText || `HTTP ${res.status}`;
  }
}

/* ---------------------------------------------------------------------------
 * Site gate
 *
 * The deployed instance sits behind one shared password (see notekit/auth.py).
 * The server hands back a token derived from that password; every subsequent
 * request carries it. Locally SITE_PASSWORD is unset, the server reports the
 * gate as off, and none of this does anything.
 * ------------------------------------------------------------------------ */

const TOKEN_KEY = "notekit.site-token";

/** Thrown when the gate rejects us, so the UI can show the password screen
 * instead of a generic error toast. */
export class SiteAuthError extends Error {
  constructor(message = "Enter the site password to continue.") {
    super(message);
    this.name = "SiteAuthError";
  }
}

export function siteToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    // Private browsing can throw on access rather than return null.
    return null;
  }
}

function storeToken(token: string | null): void {
  if (typeof window === "undefined") return;
  try {
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* nothing useful to do; the request will just be re-prompted */
  }
}

export function clearSiteToken(): void {
  storeToken(null);
}

/** Is this instance gated, and does the token we hold still work? */
export async function gateStatus(): Promise<{
  required: boolean;
  unlocked: boolean;
}> {
  const res = await fetch(`${API_BASE}/api/auth`, { cache: "no-store" });
  if (!res.ok) throw new Error(await readError(res));
  const { required } = (await res.json()) as { required: boolean };
  if (!required) return { required: false, unlocked: true };

  const token = siteToken();
  if (!token) return { required: true, unlocked: false };

  // A stored token is not proof. The password may have been rotated since.
  const probe = await fetch(`${API_BASE}/api/namespaces`, {
    cache: "no-store",
    headers: { "X-Site-Token": token },
  });
  if (probe.status === 401) {
    clearSiteToken();
    return { required: true, unlocked: false };
  }
  return { required: true, unlocked: true };
}

/** Exchange the password for a token. Throws SiteAuthError if it is wrong. */
export async function unlock(password: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/auth`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
  });
  if (res.status === 401) throw new SiteAuthError("That password is not right.");
  if (!res.ok) throw new Error(await readError(res));
  const { token } = (await res.json()) as { token: string };
  storeToken(token);
}

/** Every call below goes through here, so the token is attached in exactly one
 * place and a 401 always surfaces as SiteAuthError rather than as whatever the
 * individual caller happened to do with a bad response. */
async function request(path: string, init: RequestInit = {}): Promise<Response> {
  const token = siteToken();
  let options = init;
  if (token) {
    const headers = new Headers(init.headers);
    headers.set("X-Site-Token", token);
    options = { ...init, headers };
  }

  // The session is an httpOnly cookie, so every call has to be told to send
  // it; fetch omits credentials cross-origin by default.
  const res = await fetch(`${API_BASE}${path}`, { credentials: "include", ...options });
  // Only the instance gate's 401 means "show the password screen". A failed
  // sign-in is also a 401, and treating it as the gate told someone who had
  // mistyped their own password to enter the site password instead.
  if (res.status === 401 && res.headers.get("X-Site-Gate")) {
    // Stale or absent: drop it so the gate prompts again rather than looping.
    clearSiteToken();
    throw new SiteAuthError();
  }
  return res;
}

export async function getHealth(): Promise<{
  status: string;
  database: string;
}> {
  const res = await request(`/api/health`, { cache: "no-store" });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function getNamespaces(user: string): Promise<NamespaceInfo[]> {
  const res = await request(`/api/namespaces?user=${encodeURIComponent(user)}`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function listCourses(
  user: string,
): Promise<SavedCourseSummary[]> {
  const q = encodeURIComponent(user.trim() || "anonymous");
  const res = await request(`/api/courses?user=${q}`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

/** Pull courses saved under older browser ids onto the current identity. */
export async function claimCourses(
  user: string,
  aliases: string[],
): Promise<SavedCourseSummary[]> {
  const res = await request(`/api/courses/claim`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user, aliases }),
  });
  if (!res.ok) throw new Error(await readError(res));
  const data = (await res.json()) as {
    moved: number;
    courses: SavedCourseSummary[];
  };
  return data.courses;
}

export async function getCourse(id: number, user: string): Promise<SavedCourse> {
  const res = await request(`/api/courses/${id}?user=${encodeURIComponent(user)}`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function deleteCourse(id: number, user: string): Promise<void> {
  const res = await request(`/api/courses/${id}?user=${encodeURIComponent(user)}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error(await readError(res));
}

/** Undo a delete, while the course is still recoverable. */
export async function restoreCourse(id: number, user: string): Promise<void> {
  const res = await request(
    `/api/courses/${id}/restore?user=${encodeURIComponent(user)}`,
    { method: "POST" },
  );
  if (!res.ok) throw new Error(await readError(res));
}

export async function saveProgress(
  id: number,
  user: string,
  progress: CourseProgress,
): Promise<void> {
  const res = await request(`/api/courses/${id}/progress`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      user,
      modules_read: progress.modules_read ?? [],
      bookmark: progress.bookmark ?? null,
    }),
  });
  if (!res.ok) throw new Error(await readError(res));
}

export async function cancelCourse(id: number, user: string): Promise<void> {
  const res = await request(`/api/courses/${id}/cancel?user=${encodeURIComponent(user)}`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(await readError(res));
}

/** Ask about a highlighted span, answered from that section's own sources. */
export async function explainSelection(input: {
  courseId: number;
  moduleIndex: number;
  highlighted: string;
  question?: string;
  user: string;
}): Promise<{ answer: string; estimated_cost_usd: number }> {
  const res = await request(`/api/explain`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      course_id: input.courseId,
      module_index: input.moduleIndex,
      highlighted: input.highlighted,
      question: input.question || null,
      user: input.user,
    }),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function getStyle(user: string): Promise<StyleProfile | null> {
  const res = await request(`/api/style/${encodeURIComponent(user)}`, {
    cache: "no-store",
  });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function learnStyle(
  user: string,
  sample: string,
): Promise<StyleProfile> {
  const res = await request(`/api/style/learn`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user, sample }),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function uploadFiles(
  user: string,
  topic: string,
  files: File[],
): Promise<UploadResult> {
  const form = new FormData();
  form.append("user", user);
  form.append("topic", topic);
  for (const file of files) form.append("files", file);
  const res = await request(`/api/upload`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

async function* readSseStream(
  res: Response,
): AsyncGenerator<CourseEvent> {
  if (!res.body) throw new Error("No response body from course stream");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";

    for (const frame of frames) {
      for (const line of frame.split("\n")) {
        if (!line.startsWith("data: ")) continue;
        const payload = line.slice(6).trim();
        if (!payload || payload === "[DONE]") continue;
        yield JSON.parse(payload) as CourseEvent;
      }
    }
  }

  if (buffer.trim()) {
    for (const line of buffer.split("\n")) {
      if (!line.startsWith("data: ")) continue;
      const payload = line.slice(6).trim();
      if (!payload) continue;
      yield JSON.parse(payload) as CourseEvent;
    }
  }
}

export type Account = {
  id: number;
  email: string;
  display_name: string;
  /** The storage key this account's courses live under. */
  key: string;
};

/** Who the caller is. Answers for signed-out readers too, so there is no error path. */
export async function whoAmI(): Promise<Account | null> {
  const res = await request(`/api/me`, { cache: "no-store" });
  if (!res.ok) return null;
  const data = await res.json();
  return data.signed_in ? (data as Account) : null;
}

export async function registerAccount(input: {
  email: string;
  password: string;
  display_name?: string;
  claim?: string[];
}): Promise<Account> {
  const res = await request(`/api/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function signIn(input: {
  email: string;
  password: string;
  claim?: string[];
}): Promise<Account> {
  const res = await request(`/api/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function signOut(): Promise<void> {
  await request(`/api/logout`, { method: "POST" });
}

export async function setAccountName(display_name: string): Promise<void> {
  const res = await request(`/api/me`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ display_name }),
  });
  if (!res.ok) throw new Error(await readError(res));
}

/** Own courses and indexed subjects matching the text so far. Instant. */
export async function suggestInstant(
  q: string,
  user: string,
): Promise<{ history: { id: number; label: string }[]; topics: { slug: string; label: string }[] }> {
  const res = await request(
    `/api/suggest?q=${encodeURIComponent(q)}&user=${encodeURIComponent(user)}`,
    { cache: "no-store" },
  );
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

/** Goals a learner typing this might mean. One small model call, cached. */
export async function suggestRelated(q: string, user: string): Promise<string[]> {
  const res = await request(
    `/api/suggest/related?q=${encodeURIComponent(q)}&user=${encodeURIComponent(user)}`,
    { cache: "no-store" },
  );
  if (!res.ok) throw new Error(await readError(res));
  return (await res.json()).goals;
}

/** Plan an outline without writing anything. Cheap, so revising is free. */
export async function planCourse(input: {
  goal: string;
  user: string;
  preferences?: NotePreferences | null;
}): Promise<Syllabus> {
  const res = await request(`/api/plan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

/** Fetch the corpus an outline needs and list it. Slow for a new subject. */
export async function gatherSources(input: {
  syllabus: Syllabus;
  user: string;
  namespace?: string | null;
}): Promise<{ namespace: string; documents: SourceDocument[] }> {
  const res = await request(`/api/sources`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

/** Index one page or PDF the reader chose into the course's corpus. */
export async function addSourceUrl(input: {
  url: string;
  namespace: string;
  user: string;
}): Promise<SourceDocument> {
  const res = await request(`/api/sources/url`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

/** Parse an SSE body from POST /api/course into typed events. */
export async function* streamCourse(
  input: CourseRequest,
  signal?: AbortSignal,
): AsyncGenerator<CourseEvent> {
  const res = await request(`/api/course`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(input),
    signal,
  });

  if (!res.ok) throw new Error(await readError(res));
  yield* readSseStream(res);
}

/** Resume missing modules for a partial course. */
export async function* resumeCourse(
  id: number,
  user: string,
  signal?: AbortSignal,
): AsyncGenerator<CourseEvent> {
  const res = await request(`/api/courses/${id}/resume?user=${encodeURIComponent(user)}`, {
    method: "POST",
    headers: { Accept: "text/event-stream" },
    signal,
  });

  if (!res.ok) throw new Error(await readError(res));
  yield* readSseStream(res);
}
