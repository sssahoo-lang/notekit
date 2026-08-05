import type {
  CourseEvent,
  CourseRequest,
  NamespaceInfo,
  SavedCourse,
  SavedCourseSummary,
  StyleProfile,
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

export async function getHealth(): Promise<{
  status: string;
  database: string;
}> {
  const res = await fetch(`${API_BASE}/api/health`, { cache: "no-store" });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function getNamespaces(): Promise<NamespaceInfo[]> {
  const res = await fetch(`${API_BASE}/api/namespaces`, { cache: "no-store" });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function listCourses(
  user: string,
): Promise<SavedCourseSummary[]> {
  const q = encodeURIComponent(user.trim() || "anonymous");
  const res = await fetch(`${API_BASE}/api/courses?user=${q}`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function getCourse(id: number): Promise<SavedCourse> {
  const res = await fetch(`${API_BASE}/api/courses/${id}`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function deleteCourse(
  id: number,
  user?: string,
): Promise<void> {
  const q = user?.trim()
    ? `?user=${encodeURIComponent(user.trim())}`
    : "";
  const res = await fetch(`${API_BASE}/api/courses/${id}${q}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error(await readError(res));
}

export async function getStyle(user: string): Promise<StyleProfile | null> {
  const res = await fetch(`${API_BASE}/api/style/${encodeURIComponent(user)}`, {
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
  const res = await fetch(`${API_BASE}/api/style/learn`, {
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
  const res = await fetch(`${API_BASE}/api/upload`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

/** Parse an SSE body from POST /api/course into typed events. */
export async function* streamCourse(
  request: CourseRequest,
  signal?: AbortSignal,
): AsyncGenerator<CourseEvent> {
  const res = await fetch(`${API_BASE}/api/course`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(request),
    signal,
  });

  if (!res.ok) throw new Error(await readError(res));
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
