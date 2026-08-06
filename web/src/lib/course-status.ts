import type { GenerationStatus, SavedCourseSummary } from "@/lib/types";

export function readCount(course: SavedCourseSummary): number {
  const read = course.progress?.modules_read;
  return Array.isArray(read) ? read.length : 0;
}

export function plannedCount(course: SavedCourseSummary): number {
  if (typeof course.planned_count === "number" && course.planned_count > 0) {
    return course.planned_count;
  }
  if (course.module_titles?.length) return course.module_titles.length;
  return course.module_count;
}

export function isFinishedReading(course: SavedCourseSummary): boolean {
  const total = plannedCount(course);
  return total > 0 && readCount(course) >= total;
}

/** True when the course has at least one section with real notes. */
export function hasReadableNotes(course: SavedCourseSummary): boolean {
  if (typeof course.usable_count === "number") return course.usable_count > 0;
  return course.module_count > 0;
}

export function generationStatus(
  course: SavedCourseSummary,
): GenerationStatus {
  return course.generation_status ?? "complete";
}

export type LibraryBadge =
  | "generating"
  | "partial"
  | "ready"
  | "finished"
  | "empty";

export function libraryBadge(course: SavedCourseSummary): LibraryBadge {
  const status = generationStatus(course);
  if (status === "generating") return "generating";
  if (status === "partial") return "partial";
  if (!hasReadableNotes(course)) return "empty";
  if (isFinishedReading(course)) return "finished";
  return "ready";
}

export function relativeWhen(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const minutes = Math.round((Date.now() - then) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.round(hours / 24);
  if (days < 7) return `${days} day${days === 1 ? "" : "s"} ago`;
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
  }).format(then);
}

/** Most recent course that still has reading or generation left. */
export function pickContinueCourse(
  courses: SavedCourseSummary[],
): SavedCourseSummary | null {
  for (const course of courses) {
    const status = generationStatus(course);
    if (status === "generating" || status === "partial") return course;
    if (hasReadableNotes(course) && !isFinishedReading(course)) return course;
  }
  return null;
}

/** What to call a course in the UI: the planner's title, else what was typed. */
export function courseLabel(course: {
  title?: string;
  goal: string;
}): string {
  return course.title?.trim() || course.goal;
}

/** Reading estimate at 200 words per minute, or null when nothing is written. */
export function readingMinutes(wordCount?: number): number | null {
  if (!wordCount) return null;
  return Math.max(1, Math.round(wordCount / 200));
}
