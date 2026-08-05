"use client";

import { Button } from "@/components/ui/button";
import {
  libraryBadge,
  plannedCount,
  readCount,
  relativeWhen,
  type LibraryBadge,
} from "@/lib/course-status";
import type { SavedCourseSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

const BADGE_LABEL: Record<LibraryBadge, string> = {
  generating: "Generating",
  partial: "Partial",
  ready: "Ready",
  finished: "Finished",
  empty: "No notes",
};

/**
 * Past courses this reader has built — including incomplete ones.
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
      <section aria-labelledby="history-heading">
        <h2 id="history-heading" className="text-lg font-medium text-ink">
          History
        </h2>
        <p className="mt-2 max-w-prose text-sm text-muted-foreground">
          Every goal you start is saved here — even if generation is still
          running or only partly finished. Open anytime to keep reading.
        </p>
      </section>
    );
  }

  return (
    <section aria-labelledby="history-heading">
      <h2 id="history-heading" className="text-lg font-medium text-ink">
        History
      </h2>
      <p className="mt-1 text-sm text-muted-foreground">
        {courses.length} saved · incomplete courses stay here until you finish
        or delete them
      </p>

      <ul className="mt-4 space-y-2">
        {courses.map((course) => {
          const badge = libraryBadge(course);
          const read = readCount(course);
          const planned = plannedCount(course);
          const ready = course.usable_count ?? 0;

          let detail = relativeWhen(course.opened_at || course.created_at);
          if (badge === "generating") {
            detail = `${ready} of ${planned || "…"} ready · ${detail}`;
          } else if (badge === "partial") {
            detail = `${ready} of ${planned} ready · ${detail}`;
          } else if (badge === "finished") {
            detail = `Finished · ${detail}`;
          } else if (badge === "ready" && read > 0) {
            detail = `${read} of ${planned} read · ${detail}`;
          } else if (badge === "ready") {
            detail = `${planned} sections · ${detail}`;
          } else {
            detail = `Sources didn’t cover this · ${detail}`;
          }

          return (
            <li key={course.id}>
              <div
                className={cn(
                  "group flex items-start gap-3 rounded-xl border p-4 transition-colors duration-200",
                  activeId === course.id
                    ? "border-primary/40 bg-primary/5"
                    : "border-border/80 bg-card/80 hover:border-primary/25",
                )}
              >
                <button
                  type="button"
                  onClick={() => onOpen(course.id)}
                  className="flex-1 text-left focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-ring"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusChip badge={badge} />
                    <p className="leading-snug font-medium text-ink">
                      {course.goal}
                    </p>
                  </div>
                  <p className="mt-1.5 text-sm text-muted-foreground">
                    {detail}
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

function StatusChip({ badge }: { badge: LibraryBadge }) {
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center rounded-md px-1.5 py-0.5 font-mono text-[0.65rem] tracking-wide uppercase",
        badge === "generating" && "bg-primary/15 text-primary",
        badge === "partial" && "bg-amber-500/15 text-amber-900",
        badge === "ready" && "bg-teal-800/10 text-teal-900",
        badge === "finished" && "bg-muted text-muted-foreground",
        badge === "empty" && "bg-muted text-muted-foreground",
      )}
    >
      {badge === "generating" ? (
        <span className="mr-1 inline-block size-1.5 animate-pulse rounded-full bg-primary" />
      ) : null}
      {BADGE_LABEL[badge]}
    </span>
  );
}
