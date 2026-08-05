import type { ModuleState } from "./types";

const KEY = "notekit.lastCourse";

export type CachedCourse = {
  id: number | null;
  user: string;
  goal: string;
  summary: string | null;
  namespace: string | null;
  cost: number | null;
  modules: ModuleState[];
  savedAt: string;
};

export function saveCachedCourse(course: CachedCourse): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(KEY, JSON.stringify(course));
  } catch {
    // Quota or private mode — history DB is still the source of truth.
  }
}

export function loadCachedCourse(): CachedCourse | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return null;
    return JSON.parse(raw) as CachedCourse;
  } catch {
    return null;
  }
}

export function clearCachedCourse(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem(KEY);
}
