"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { ModuleState } from "@/lib/types";
import { cn } from "@/lib/utils";

import { AskAbout } from "./ask-about";
import { NotesBody } from "./notes-body";
import { QuizPanel } from "./quiz-panel";

type Props = {
  module: ModuleState;
  read?: boolean;
  onMarkRead?: () => void;
  onVisible?: () => void;
  /** Needed to ask about a passage; null until the course has been saved. */
  courseId?: number | null;
  userId?: string;
  expanded?: boolean;
  onToggle?: () => void;
  /** Reader-wide preference; sources stay listed either way. */
  showCitations?: boolean;
  /** Opens the next section and scrolls to it, when there is one. */
  onAdvance?: () => void;
  /** Reports the paragraph currently at the top of the reading area. */
  onParagraph?: (paragraph: number) => void;
  /** Paragraph to restore on open, from a stored bookmark. */
  restoreParagraph?: number | null;
};

/** Rough reading time. 200 wpm is the usual estimate for considered reading. */
function readingMinutes(text: string): number {
  const words = text.trim().split(/\s+/).filter(Boolean).length;
  return Math.max(1, Math.round(words / 200));
}

export function ModulePanel({
  module,
  read,
  onMarkRead,
  onVisible,
  courseId = null,
  userId,
  expanded = true,
  onToggle,
  showCitations = true,
  onAdvance,
  onParagraph,
  restoreParagraph = null,
}: Props) {
  const [activeCite, setActiveCite] = useState<number | null>(null);
  const [quizOpen, setQuizOpen] = useState(false);
  const articleRef = useRef<HTMLElement>(null);
  const proseRef = useRef<HTMLDivElement>(null);
  const chunks = module.notes?.chunks;
  const chunkMap = useMemo(
    () => new Map((chunks ?? []).map((c) => [c.id, c])),
    [chunks],
  );
  const chunkList = chunks ?? [];
  const numbering = useMemo(
    () => new Map(chunkList.map((c, i) => [c.id, i + 1])),
    [chunkList],
  );
  const activeChunk = activeCite != null ? chunkMap.get(activeCite) : null;

  const body =
    module.notes?.body ||
    (module.status === "streaming" || module.status === "pending"
      ? module.streamingText
      : "");

  const showEmptyBody =
    module.status === "done" &&
    !module.notes?.refused &&
    !module.error &&
    !body.trim();

  const canMarkRead =
    onMarkRead &&
    !read &&
    (module.status === "done" || module.status === "refused");

  // Track which paragraph is being read, so a bookmark can point at it rather
  // than at the top of a 1,400-word section.
  useEffect(() => {
    if (!onParagraph || !expanded || !proseRef.current) return;
    const paragraphs = proseRef.current.querySelectorAll("[data-paragraph]");
    if (!paragraphs.length) return;

    const observer = new IntersectionObserver(
      (entries) => {
        const top = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
        if (!top) return;
        const index = Number(
          (top.target as HTMLElement).dataset.paragraph ?? "0",
        );
        onParagraph(index);
      },
      { rootMargin: "-20% 0px -70% 0px", threshold: 0 },
    );
    paragraphs.forEach((node) => observer.observe(node));
    return () => observer.disconnect();
  }, [onParagraph, expanded, body]);

  // Restore the bookmarked paragraph once, when the section first opens.
  const restoredRef = useRef(false);
  useEffect(() => {
    if (restoredRef.current || !expanded || restoreParagraph == null) return;
    if (!proseRef.current) return;
    const target = proseRef.current.querySelector(
      `[data-paragraph="${restoreParagraph}"]`,
    );
    if (!target) return;
    restoredRef.current = true;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    target.scrollIntoView({
      behavior: reduced ? "auto" : "smooth",
      block: "center",
    });
  }, [expanded, restoreParagraph]);

  useEffect(() => {
    if (!onVisible || !articleRef.current) return;
    const node = articleRef.current;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting) onVisible();
      },
      { rootMargin: "-30% 0px -50% 0px", threshold: 0 },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [onVisible]);

  return (
    <article
      ref={articleRef}
      className="rounded-2xl border border-border/50 bg-paper/70 px-5 py-8 shadow-[0_1px_0_oklch(0.9_0.01_95)] sm:px-8"
    >
      <header className="flex flex-wrap items-start justify-between gap-3">
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={expanded}
          aria-controls={`section-body-${module.index}`}
          className="group flex min-w-0 flex-1 items-start gap-3 text-left focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-ring"
        >
          <span
            aria-hidden="true"
            className={cn(
              "mt-1.5 text-muted-foreground transition-transform duration-150 ease-out motion-reduce:transition-none",
              expanded && "rotate-90",
            )}
          >
            ›
          </span>
          <span className="min-w-0">
            <span className="block font-mono text-[0.7rem] tracking-[0.14em] text-muted-foreground uppercase">
              Section {module.index + 1}
              {read ? " · read" : ""}
              {body ? ` · ${readingMinutes(body)} min` : ""}
            </span>
            <h2 className="font-heading mt-1 text-2xl tracking-tight text-ink transition-colors group-hover:text-primary">
              {module.title}
            </h2>
          </span>
        </button>
        <StatusBadge module={module} />
      </header>

      {/* Collapsed: enough of the opening to recognise the section by. */}
      {!expanded && body ? (
        <p className="mt-3 line-clamp-2 text-sm text-muted-foreground">
          {body.replace(/\[c\d+\]/g, "").trim()}
        </p>
      ) : null}

      <div
        id={`section-body-${module.index}`}
        hidden={!expanded}
        className="mt-5"
      >

      {module.error ? (
        <p className="rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
          {module.error}
        </p>
      ) : null}

      {module.notes?.refused ? (
        <p className="rounded-lg border border-amber-700/20 bg-amber-50 px-3 py-3 text-sm text-amber-950">
          {module.notes.refusal_reason ||
            "Insufficient source material for this module."}
        </p>
      ) : null}

      {body ? (
        <div ref={proseRef}>
          <NotesBody
            text={body}
            streaming={module.status === "streaming"}
            activeId={activeCite}
            onCite={setActiveCite}
            numbering={numbering}
            hidden={!showCitations}
            className="measure font-notes text-[1.08rem] leading-[1.75] text-ink"
          />
        </div>
      ) : null}

      {body && module.status !== "streaming" ? (
        <AskAbout
          containerRef={proseRef}
          courseId={courseId}
          moduleIndex={module.index}
          userId={userId}
          sectionTitle={module.title}
        />
      ) : null}

      {showEmptyBody ? (
        <p className="text-sm text-muted-foreground">
          No notes were saved for this section.
        </p>
      ) : null}

      {module.status === "streaming" && !body ? (
        <p className="text-sm text-muted-foreground">Writing notes…</p>
      ) : null}

      {module.status === "streaming" && body ? (
        <span
          className="mt-2 inline-block h-4 w-1.5 animate-pulse bg-primary/70 align-middle"
          aria-hidden="true"
        />
      ) : null}

      {module.status === "pending" && !body ? (
        <p className="text-sm text-muted-foreground">Waiting to write…</p>
      ) : null}

      {module.status === "done" || module.status === "refused" ? (
        <div className="mt-8 flex flex-wrap items-center gap-2 border-t border-border/60 pt-5">
          {onAdvance ? (
            <Button
              type="button"
              size="sm"
              onClick={() => {
                if (!read) onMarkRead?.();
                onAdvance();
              }}
            >
              {read ? "Next section" : "Mark read & continue"} →
            </Button>
          ) : null}
          {canMarkRead ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={onMarkRead}
              className="text-muted-foreground hover:text-foreground"
            >
              {onAdvance ? "Just mark as read" : "Mark as read"}
            </Button>
          ) : null}
        </div>
      ) : null}

      {module.notes?.quiz && !module.notes.refused ? (
        <div className="mt-8 border-t border-border/60 pt-5">
          <button
            type="button"
            onClick={() => setQuizOpen((v) => !v)}
            aria-expanded={quizOpen}
            aria-controls={`quiz-${module.index}`}
            className="flex items-center gap-2 text-sm font-medium text-foreground/80 hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          >
            <span
              aria-hidden="true"
              className={cn(
                "transition-transform duration-150 ease-out motion-reduce:transition-none",
                quizOpen && "rotate-90",
              )}
            >
              ›
            </span>
            Practice questions
            <span className="font-normal text-muted-foreground">
              ({module.notes.quiz.questions.length})
            </span>
          </button>
          <div id={`quiz-${module.index}`} hidden={!quizOpen} className="mt-5">
            <QuizPanel quiz={module.notes.quiz} onCite={setActiveCite} />
          </div>
        </div>
      ) : null}

      {chunkList.length > 0 && !module.notes?.refused ? (
        <details className="mt-8 group">
          <summary className="cursor-pointer list-none text-sm font-medium text-muted-foreground transition-colors hover:text-foreground [&::-webkit-details-marker]:hidden">
            <span className="underline-offset-4 group-open:no-underline">
              Where this came from
            </span>
            <span className="ml-1.5 font-normal">({chunkList.length})</span>
          </summary>
          <ul className="mt-3 space-y-2">
            {chunkList.map((chunk) => (
              <li key={chunk.id}>
                <button
                  type="button"
                  onClick={() => setActiveCite(chunk.id)}
                  className={cn(
                    "block w-full rounded-xl border px-4 py-3 text-left transition-colors",
                    activeCite === chunk.id
                      ? "border-cite/50 bg-cite/10"
                      : "border-border/70 bg-background/50 hover:border-cite/30",
                  )}
                >
                  <div className="mb-1 flex flex-wrap items-center gap-2">
                    <Badge variant="outline" className="font-mono">
                      {numbering.get(chunk.id) ?? chunk.id}
                    </Badge>
                    <span className="text-sm font-medium">
                      {chunk.document_title}
                    </span>
                  </div>
                  <p className="line-clamp-3 text-sm text-muted-foreground">
                    {chunk.text}
                  </p>
                </button>
              </li>
            ))}
          </ul>
        </details>
      ) : null}

      {activeChunk ? (
        <aside className="mt-4 rounded-xl border border-cite/30 bg-cite/8 px-4 py-3">
          <div className="mb-1 flex flex-wrap items-center gap-2">
            <Badge className="bg-cite text-cite-foreground hover:bg-cite">
              Source {numbering.get(activeChunk.id) ?? activeChunk.id}
            </Badge>
            {activeChunk.document_url ? (
              <a
                href={activeChunk.document_url}
                target="_blank"
                rel="noreferrer"
                className="text-sm font-medium underline-offset-4 hover:underline"
              >
                {activeChunk.document_title}
              </a>
            ) : (
              <span className="text-sm font-medium">
                {activeChunk.document_title}
              </span>
            )}
          </div>
          <p className="text-sm leading-relaxed text-ink/80">{activeChunk.text}</p>
        </aside>
      ) : null}
      </div>
    </article>
  );
}

function StatusBadge({ module }: { module: ModuleState }) {
  switch (module.status) {
    case "pending":
      return <Badge variant="outline">Queued</Badge>;
    case "streaming":
      return <Badge className="bg-primary/90">Writing</Badge>;
    case "refused":
      return (
        <Badge variant="outline" className="border-amber-700/30 text-amber-900">
          Couldn&apos;t cover
        </Badge>
      );
    case "error":
      return <Badge variant="destructive">Error</Badge>;
    case "done":
      return null;
  }
}
