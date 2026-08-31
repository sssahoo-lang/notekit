"use client";

import { ProgressBar } from "@/components/progress-bar";
import { Button } from "@/components/ui/button";
import { guidanceFor } from "@/lib/run-error";
import { cn } from "@/lib/utils";

export type RunPhase =
  | "idle"
  | "planning"
  | "gathering"
  | "writing"
  | "done"
  | "error";

/**
 * What is happening, in the reader's words.
 *
 * Building a course takes around forty seconds, so silence reads as a hang.
 * Each phase says what is happening and roughly how long it lasts, and the
 * whole thing is a polite live region so a screen reader announces changes
 * without interrupting whatever is being read.
 */
const PHASES: Record<
  Exclude<RunPhase, "idle" | "done" | "error">,
  { label: string; detail: string }
> = {
  planning: {
    label: "Planning your course",
    detail: "Working out which topics to cover. A few seconds.",
  },
  gathering: {
    label: "Gathering sources",
    detail:
      "Finding and reading real material to write from. Only happens the first time you study a topic.",
  },
  writing: {
    label: "Writing your notes",
    detail: "Sections appear below as they finish, so you can start reading straight away.",
  },
};

type Props = {
  phase: RunPhase;
  detail?: string;
  modulesDone?: number;
  modulesTotal?: number;
  onCancel?: () => void;
};

export function RunStatus({
  phase,
  detail,
  modulesDone = 0,
  modulesTotal = 0,
  onCancel,
}: Props) {
  if (phase === "idle" || phase === "error") return null;

  if (phase === "done") {
    return (
      <p
        role="status"
        aria-live="polite"
        className="text-sm font-medium text-teal-900"
      >
        Your notes are ready and saved. Come back anytime from History.
      </p>
    );
  }

  const copy = PHASES[phase];
  const showCount = phase === "writing" && modulesTotal > 0;

  return (
    <div
      role="status"
      aria-live="polite"
      className="rounded-xl border border-border bg-card p-4"
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <span
            aria-hidden="true"
            className="mt-1.5 size-2 shrink-0 animate-pulse rounded-full bg-primary"
          />
          <div>
            <p className="font-medium text-foreground">
              {copy.label}
              {showCount ? `, ${modulesDone} of ${modulesTotal} done` : ""}
            </p>
            <p className="mt-0.5 text-sm text-muted-foreground">
              {detail || copy.detail}
            </p>
          </div>
        </div>
        {onCancel ? (
          <Button type="button" variant="ghost" size="sm" onClick={onCancel}>
            Stop
          </Button>
        ) : null}
      </div>

      {showCount ? (
        <ProgressBar
          className="mt-3"
          value={modulesDone}
          max={modulesTotal}
          label="Sections written"
        />
      ) : null}
    </div>
  );
}

/**
 * A failure the reader can act on.
 *
 * Every message says what went wrong and what to do next. The backend's own
 * wording is kept in the disclosure, but framed rather than dumped raw, and
 * the retry button appears only when retrying could actually succeed. See
 * lib/run-error.ts for why those are two separate questions.
 */
export function RunError({
  message,
  onRetry,
  className,
}: {
  message: string;
  onRetry?: () => void;
  className?: string;
}) {
  const guidance = guidanceFor(message);
  const canRetry = Boolean(onRetry) && guidance.retryable;

  return (
    <div
      role="alert"
      className={cn(
        "rounded-xl border border-destructive/30 bg-destructive/5 p-4",
        className,
      )}
    >
      <p className="font-medium text-destructive">{guidance.headline}</p>
      <p className="mt-1 text-sm text-foreground/80">{guidance.next}</p>
      <details className="mt-2">
        <summary className="cursor-pointer text-xs text-muted-foreground hover:text-foreground">
          Technical detail
        </summary>
        <p className="mt-1 font-mono text-xs break-words text-muted-foreground">
          {message}
        </p>
      </details>
      {canRetry ? (
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="mt-3"
          onClick={onRetry}
        >
          Try again
        </Button>
      ) : null}
    </div>
  );
}
