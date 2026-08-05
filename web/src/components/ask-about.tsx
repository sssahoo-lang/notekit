"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { CitedText } from "@/components/cited-text";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { explainSelection } from "@/lib/api";

/** Shorter than this is usually a stray click, not a real highlight. */
const MIN_SELECTION = 8;

type Selection = { text: string; top: number; left: number };

/**
 * Watch for a meaningful text selection inside one element.
 *
 * Returns viewport coordinates so the prompt can sit beside what was
 * highlighted. Cleared on scroll, because a button pinned to stale coordinates
 * ends up pointing at the wrong sentence.
 */
function useSelectionIn(ref: React.RefObject<HTMLElement | null>) {
  const [selection, setSelection] = useState<Selection | null>(null);

  useEffect(() => {
    function read() {
      const sel = window.getSelection();
      if (!sel || sel.isCollapsed || sel.rangeCount === 0) {
        setSelection(null);
        return;
      }
      const text = sel.toString().trim();
      const range = sel.getRangeAt(0);
      if (
        text.length < MIN_SELECTION ||
        !ref.current?.contains(range.commonAncestorContainer)
      ) {
        setSelection(null);
        return;
      }
      const rect = range.getBoundingClientRect();
      setSelection({ text, top: rect.top, left: rect.left + rect.width / 2 });
    }

    const clear = () => setSelection(null);
    document.addEventListener("selectionchange", read);
    window.addEventListener("scroll", clear, true);
    return () => {
      document.removeEventListener("selectionchange", read);
      window.removeEventListener("scroll", clear, true);
    };
  }, [ref]);

  return [selection, () => setSelection(null)] as const;
}

type Props = {
  containerRef: React.RefObject<HTMLElement | null>;
  courseId: number | null;
  moduleIndex: number;
  userId?: string;
  /** Fallback text when asking about the section as a whole. */
  sectionTitle: string;
};

/**
 * "I don't follow this" — ask about a highlighted sentence.
 *
 * The answer comes from the same passages the section was written from, so
 * asking for a simpler explanation cannot pull in claims the sources never
 * made. If the passages don't cover the question, the answer says so.
 */
export function AskAbout({
  containerRef,
  courseId,
  moduleIndex,
  userId,
  sectionTitle,
}: Props) {
  const [selection, clearSelection] = useSelectionIn(containerRef);
  const [asking, setAsking] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeCite, setActiveCite] = useState<number | null>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  const open = useCallback((text: string) => {
    setAsking(text);
    setAnswer(null);
    setError(null);
    setQuestion("");
    clearSelection();
    window.getSelection()?.removeAllRanges();
    // Move focus into the panel so keyboard and screen reader users land where
    // the new content appeared.
    requestAnimationFrame(() => panelRef.current?.focus());
  }, [clearSelection]);

  async function ask() {
    if (!asking || courseId == null) return;
    setBusy(true);
    setError(null);
    try {
      const result = await explainSelection({
        courseId,
        moduleIndex,
        highlighted: asking,
        question: question.trim() || undefined,
        user: userId,
      });
      setAnswer(result.answer);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  // Nothing to explain from until the course has been saved with its sources.
  if (courseId == null) return null;

  return (
    <>
      {selection && !asking ? (
        <div
          className="fixed z-50 -translate-x-1/2 -translate-y-full pb-2"
          style={{ top: selection.top, left: selection.left }}
        >
          <Button
            type="button"
            size="sm"
            className="shadow-lg"
            onClick={() => open(selection.text)}
          >
            Explain this
          </Button>
        </div>
      ) : null}

      <div className="mt-6">
        {!asking ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            // Buttons default to nowrap; this label is wider than a phone.
            className="h-auto max-w-full whitespace-normal py-1.5 text-left text-muted-foreground hover:text-foreground"
            onClick={() => open(sectionTitle)}
          >
            Stuck? Ask about this section
          </Button>
        ) : (
          <div
            ref={panelRef}
            tabIndex={-1}
            role="group"
            aria-label="Ask about this passage"
            className="rounded-xl border border-primary/30 bg-primary/[0.04] p-4 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          >
            <p className="text-xs tracking-wide text-muted-foreground uppercase">
              You highlighted
            </p>
            <blockquote className="mt-1 border-l-2 border-primary/40 pl-3 text-sm text-foreground/85 italic">
              {asking.length > 320 ? `${asking.slice(0, 320)}…` : asking}
            </blockquote>

            <div className="mt-3 space-y-2">
              <Label htmlFor={`q-${moduleIndex}`} className="text-sm">
                What would you like to know? (optional)
              </Label>
              <Input
                id={`q-${moduleIndex}`}
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="e.g. what does this mean in plain terms?"
                disabled={busy}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !busy) void ask();
                }}
              />
            </div>

            <div className="mt-3 flex flex-wrap gap-2">
              <Button type="button" size="sm" onClick={ask} disabled={busy}>
                {busy ? "Looking it up…" : "Explain"}
              </Button>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                onClick={() => {
                  setAsking(null);
                  setAnswer(null);
                  setError(null);
                }}
              >
                Close
              </Button>
            </div>

            {busy ? (
              <p role="status" aria-live="polite" className="mt-3 text-sm text-muted-foreground">
                Checking what your sources say…
              </p>
            ) : null}

            {error ? (
              <p role="alert" className="mt-3 text-sm text-destructive">
                Couldn&apos;t answer that just now. {error}
              </p>
            ) : null}

            {answer ? (
              <div role="status" aria-live="polite" className="mt-4">
                <CitedText
                  text={answer}
                  activeId={activeCite}
                  onCite={setActiveCite}
                  className="measure font-notes text-[1.02rem] leading-[1.7] text-ink"
                />
                <p className="mt-3 text-xs text-muted-foreground">
                  Answered only from this section&apos;s sources — the same ones
                  the notes were written from.
                </p>
              </div>
            ) : null}
          </div>
        )}
      </div>
    </>
  );
}
