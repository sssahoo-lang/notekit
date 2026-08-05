"use client";

import { Button } from "@/components/ui/button";
import {
  generationStatus,
  hasReadableNotes,
  plannedCount,
  readCount,
  relativeWhen,
} from "@/lib/course-status";
import type { SavedCourseSummary } from "@/lib/types";

/**
 * The most recent unfinished course, offered before anything else.
 *
 * Someone returning to study wants to carry on, not fill in a form.
 */
export function ContinueCard({
  course,
  onOpen,
}: {
  course: SavedCourseSummary;
  onOpen: (id: number) => void;
}) {
  const read = readCount(course);
  const total = plannedCount(course);
  const nextSection = course.module_titles?.[read];
  const started = read > 0;
  const status = generationStatus(course);
  const generating = status === "generating";
  const partial = status === "partial";

  let heading = "Your latest course";
  let cta = "Start reading";
  if (generating) {
    heading = "Still writing";
    cta = "Open course";
  } else if (partial) {
    heading = "Continue studying";
    cta = hasReadableNotes(course) ? "Continue studying" : "Resume generation";
  } else if (started) {
    heading = "Continue studying";
    cta = "Continue studying";
  }

  let meta = "";
  if (generating) {
    meta = `${course.usable_count ?? 0} of ${total || "…"} sections ready · updating in the background`;
  } else if (partial) {
    meta = `${course.usable_count ?? 0} of ${total} sections ready · generation paused`;
  } else if (started) {
    meta = `${read} of ${total} sections read · last opened ${relativeWhen(course.opened_at || course.created_at)}`;
  } else {
    meta = `${total} section${total === 1 ? "" : "s"} ready to read`;
  }

  return (
    <section
      aria-labelledby="continue-heading"
      className="animate-in fade-in slide-in-from-bottom-2 duration-500 rounded-2xl border border-primary/20 bg-gradient-to-br from-primary/[0.06] to-transparent p-5 sm:p-6"
    >
      <h2
        id="continue-heading"
        className="font-mono text-xs tracking-[0.14em] text-primary uppercase"
      >
        {heading}
      </h2>

      <p className="mt-2 text-xl leading-snug font-medium text-ink">
        {course.goal}
      </p>

      <p className="mt-1.5 text-sm text-muted-foreground">{meta}</p>

      {nextSection && !generating ? (
        <p className="mt-3 text-sm text-foreground/80">
          <span className="text-muted-foreground">Next up: </span>
          {nextSection}
        </p>
      ) : null}

      {total > 0 ? (
        <div
          className="mt-4 h-1.5 overflow-hidden rounded-full bg-primary/12"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={total}
          aria-valuenow={generating ? (course.usable_count ?? 0) : read}
          aria-label={
            generating
              ? `${course.usable_count ?? 0} of ${total} sections ready`
              : `${read} of ${total} sections read`
          }
        >
          <div
            className="h-full rounded-full bg-primary transition-[width] duration-500 ease-out"
            style={{
              width: `${Math.round(
                ((generating ? (course.usable_count ?? 0) : read) / total) * 100,
              )}%`,
            }}
          />
        </div>
      ) : null}

      <Button className="mt-5" onClick={() => onOpen(course.id)}>
        {cta}
      </Button>
    </section>
  );
}
