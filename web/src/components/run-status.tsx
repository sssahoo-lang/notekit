"use client";

import { Button } from "@/components/ui/button";
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
    detail: "Working out which topics to cover — a few seconds.",
  },
  gathering: {
    label: "Gathering sources",
    detail:
      "Finding and reading real material to write from. Only happens the first time you study a topic.",
  },
  writing: {
    label: "Writing your notes",
    detail: "Sections appear below as they finish — you can start reading straight away.",
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
        Your notes are ready and saved — come back anytime from History.
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
              {showCount ? ` — ${modulesDone} of ${modulesTotal} done` : ""}
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
        <div
          className="mt-3 h-1.5 overflow-hidden rounded-full bg-muted"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={modulesTotal}
          aria-valuenow={modulesDone}
          aria-label="Sections written"
        >
          <div
            className="h-full rounded-full bg-primary transition-[width] duration-500"
            style={{
              width: `${Math.round((modulesDone / Math.max(modulesTotal, 1)) * 100)}%`,
            }}
          />
        </div>
      ) : null}
    </div>
  );
}

/**
 * A failure the reader can act on.
 *
 * Every message says what went wrong and what to do next. The backend's own
 * wording is kept, but framed rather than dumped raw.
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
      {onRetry ? (
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

function guidanceFor(message: string): { headline: string; next: string } {
  const lower = message.toLowerCase();

  if (lower.includes("fetch") || lower.includes("networkerror") || lower.includes("failed to fetch")) {
    return {
      headline: "Can't reach the NoteKit service",
      next: "The backend isn't responding. Start it with `uv run uvicorn notekit.api:app --port 8000`, then try again.",
    };
  }
  if (lower.includes("database")) {
    return {
      headline: "The database isn't running",
      next: "Start it with `docker compose up -d` from the project folder, then try again.",
    };
  }
  if (lower.includes("api_key") || lower.includes("authentication") || lower.includes("401")) {
    return {
      headline: "The API key is missing or invalid",
      next: "Check that ANTHROPIC_API_KEY is set in your .env file, then restart the backend.",
    };
  }
  if (lower.includes("rate") || lower.includes("429")) {
    return {
      headline: "Too many requests right now",
      next: "The model is rate limiting. Wait a minute and try again.",
    };
  }
  if (lower.includes("no such") || lower.includes("404") || lower.includes("not found")) {
    return {
      headline: "That isn't there any more",
      next: "It may have been deleted. Go back and pick something else.",
    };
  }
  return {
    headline: "Something went wrong",
    next: "The step didn't finish. Trying again usually works; if it keeps failing, the detail below will say why.",
  };
}
