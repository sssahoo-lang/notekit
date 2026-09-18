"use client";

import { useEffect, useRef, useState } from "react";

import { suggestInstant, suggestRelated } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * Suggestions under the goal box, as the reader types.
 *
 * Three groups, in the order a reader is likely to want them. Their own
 * courses come first, because typing a subject you already built usually
 * means you want it back. Subjects already indexed come next: those build
 * at once, with no minutes of fetching. Related ideas come last, after a
 * pause, because they cost a model call and a text box should not spend
 * money per keystroke.
 *
 * Choosing a suggestion fills the box; it does not submit, because the
 * reader may still want the options below it.
 */

type Props = {
  query: string;
  userId: string;
  onPick: (goal: string) => void;
  onOpenCourse: (id: number) => void;
};

type Instant = Awaited<ReturnType<typeof suggestInstant>>;

const MIN_CHARS = 3;
const RELATED_DELAY_MS = 600;

export function GoalSuggestions({ query, userId, onPick, onOpenCourse }: Props) {
  const [instant, setInstant] = useState<Instant>({ history: [], topics: [] });
  const [related, setRelated] = useState<string[]>([]);
  // Which text the related ideas were fetched for. "Thinking" is derived
  // from it rather than set in the effect: results are stale, and a call is
  // pending, exactly when this lags behind what is typed.
  const [relatedFor, setRelatedFor] = useState<string | null>(null);
  const [dismissedFor, setDismissedFor] = useState<string | null>(null);
  const latest = useRef(0);

  const q = query.trim();
  const active = q.length >= MIN_CHARS && dismissedFor !== q;
  const thinking = active && relatedFor !== q;

  useEffect(() => {
    if (!active) return;
    const seq = ++latest.current;
    void suggestInstant(q, userId)
      .then((r) => {
        if (seq === latest.current) setInstant(r);
      })
      .catch(() => undefined);

    const timer = window.setTimeout(() => {
      void suggestRelated(q, userId)
        .then((goals) => {
          if (seq === latest.current) setRelated(goals);
        })
        .catch(() => {
          if (seq === latest.current) setRelated([]);
        })
        .finally(() => {
          if (seq === latest.current) setRelatedFor(q);
        });
    }, RELATED_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [q, userId, active]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setDismissedFor(q);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [q]);

  if (!active) return null;
  const shownRelated = relatedFor === q ? related : [];
  const empty = !instant.history.length && !instant.topics.length && !shownRelated.length;
  if (empty && !thinking) return null;

  const item =
    "block w-full rounded-md px-3 py-1.5 text-left text-sm text-foreground/85 hover:bg-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring";
  const heading = "px-3 pt-2 pb-1 font-mono text-[0.65rem] tracking-[0.14em] text-muted-foreground uppercase";

  return (
    <div
      role="listbox"
      aria-label="Suggestions"
      className={cn(
        "mt-2 rounded-xl border border-border/80 bg-card/95 py-1 shadow-sm",
        "max-h-72 overflow-y-auto",
      )}
    >
      {instant.history.length ? (
        <div>
          <div className={heading}>Your courses</div>
          {instant.history.map((h) => (
            <button key={h.id} type="button" role="option" aria-selected={false} className={item} onClick={() => onOpenCourse(h.id)}>
              {h.label}
              <span className="ml-2 text-xs text-muted-foreground">open</span>
            </button>
          ))}
        </div>
      ) : null}

      {instant.topics.length ? (
        <div>
          <div className={heading}>Already gathered, builds at once</div>
          {instant.topics.map((t) => (
            <button key={t.slug} type="button" role="option" aria-selected={false} className={item} onClick={() => onPick(t.label)}>
              {t.label}
            </button>
          ))}
        </div>
      ) : null}

      {shownRelated.length || thinking ? (
        <div>
          <div className={heading}>Related ideas</div>
          {shownRelated.map((g) => (
            <button key={g} type="button" role="option" aria-selected={false} className={item} onClick={() => onPick(g)}>
              {g}
            </button>
          ))}
          {thinking ? (
            <div className="px-3 py-1.5 text-sm text-muted-foreground" role="status">
              Thinking of related goals…
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
