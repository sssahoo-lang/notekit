"use client";

import { Button } from "@/components/ui/button";
import { isFinished, readCount } from "@/components/continue-card";
import type { SavedCourseSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

function when(iso: string): string {
  try {
    return new Intl.DateTimeFormat(undefined, {
      month: "short",
      day: "numeric",
    }).format(new Date(iso));
  } catch {
    return "";
  }
}

/**
 * Everything this reader has studied.
 *
 * The empty state explains what will appear here and why it is worth having,
 * rather than showing an identity label above a blank list — which is what the
 * old history panel did, and it read like a bug.
 */
export function LibraryList({
  courses,
  activeId,
  onOpen,
  onDelete,
}: {
  courses: SavedCourseSummary[];
  activeId?: number | null;
  onOpen: (id: number) => void;
  onDelete: (id: number) => void;
}) {
  if (courses.length === 0) {
    return (
      <section aria-labelledby="library-heading">
        <h2 id="library-heading" className="text-lg font-medium text-ink">
          Your courses
        </h2>
        <p className="mt-2 max-w-prose text-sm text-muted-foreground">
          Nothing here yet. Once you build a course it&apos;s saved
          automatically, so you can close the tab and pick it up later without
          waiting for it to be written again.
        </p>
      </section>
    );
  }

  return (
    <section aria-labelledby="library-heading">
      <h2 id="library-heading" className="text-lg font-medium text-ink">
        Your courses
      </h2>
      <p className="mt-1 text-sm text-muted-foreground">
        {courses.length} saved · opening one is instant and costs nothing
      </p>

      <ul className="mt-4 space-y-2">
        {courses.map((course) => {
          const read = readCount(course);
          const done = isFinished(course);
          return (
            <li key={course.id}>
              <div
                className={cn(
                  "group flex items-start gap-3 rounded-xl border p-4 transition-colors",
                  activeId === course.id
                    ? "border-primary/40 bg-primary/5"
                    : "border-border bg-card hover:border-primary/30",
                )}
              >
                <button
                  type="button"
                  onClick={() => onOpen(course.id)}
                  className="flex-1 text-left focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-ring"
                >
                  <p className="leading-snug font-medium text-ink">
                    {course.goal}
                  </p>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {done
                      ? "Finished"
                      : read > 0
                        ? `${read} of ${course.module_count} read`
                        : `${course.module_count} sections`}
                    {" · "}
                    {when(course.created_at)}
                    {course.used_style ? " · your writing style" : ""}
                  </p>
                </button>

                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  aria-label={`Delete course: ${course.goal}`}
                  className="text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100 hover:text-destructive"
                  onClick={() => onDelete(course.id)}
                >
                  Delete
                </Button>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
