"use client";

import { Button } from "@/components/ui/button";
import type { SavedCourseSummary } from "@/lib/types";

export function readCount(course: SavedCourseSummary): number {
  const read = course.progress?.modules_read;
  return Array.isArray(read) ? read.length : 0;
}

export function isFinished(course: SavedCourseSummary): boolean {
  return course.module_count > 0 && readCount(course) >= course.module_count;
}

function relativeWhen(iso: string): string {
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

/**
 * The most recent unfinished course, offered before anything else.
 *
 * Someone returning to study wants to carry on, not fill in a form. This is the
 * first thing on the page whenever there is something to carry on with.
 */
export function ContinueCard({
  course,
  onOpen,
}: {
  course: SavedCourseSummary;
  onOpen: (id: number) => void;
}) {
  const read = readCount(course);
  const total = course.module_count;
  const nextSection = course.module_titles?.[read];
  const started = read > 0;

  return (
    <section
      aria-labelledby="continue-heading"
      className="rounded-2xl border border-primary/25 bg-primary/[0.04] p-5 sm:p-6"
    >
      <h2
        id="continue-heading"
        className="font-mono text-xs tracking-[0.14em] text-primary uppercase"
      >
        {started ? "Pick up where you left off" : "Ready when you are"}
      </h2>

      <p className="mt-2 text-xl leading-snug font-medium text-ink">
        {course.goal}
      </p>

      <p className="mt-1.5 text-sm text-muted-foreground">
        {started
          ? `${read} of ${total} sections read · last opened ${relativeWhen(course.opened_at || course.created_at)}`
          : `${total} section${total === 1 ? "" : "s"} · not started yet`}
      </p>

      {nextSection ? (
        <p className="mt-3 text-sm text-foreground/80">
          <span className="text-muted-foreground">Next up: </span>
          {nextSection}
        </p>
      ) : null}

      {total > 0 ? (
        <div
          className="mt-4 h-2 overflow-hidden rounded-full bg-primary/12"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={total}
          aria-valuenow={read}
          aria-label={`${read} of ${total} sections read`}
        >
          <div
            className="h-full rounded-full bg-primary transition-[width] duration-500"
            style={{ width: `${Math.round((read / total) * 100)}%` }}
          />
        </div>
      ) : null}

      <Button className="mt-5" onClick={() => onOpen(course.id)}>
        {started ? "Continue studying" : "Start reading"}
      </Button>
    </section>
  );
}
