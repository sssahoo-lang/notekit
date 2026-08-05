"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { ModuleState } from "@/lib/types";
import { cn } from "@/lib/utils";

import { CitedText } from "./cited-text";
import { QuizPanel } from "./quiz-panel";

type Props = {
  module: ModuleState;
  read?: boolean;
  onMarkRead?: () => void;
  onVisible?: () => void;
};

export function ModulePanel({ module, read, onMarkRead, onVisible }: Props) {
  const [activeCite, setActiveCite] = useState<number | null>(null);
  const articleRef = useRef<HTMLElement>(null);
  const chunks = module.notes?.chunks;
  const chunkMap = useMemo(
    () => new Map((chunks ?? []).map((c) => [c.id, c])),
    [chunks],
  );
  const chunkList = chunks ?? [];
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
      <header className="mb-5 flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <p className="font-mono text-[0.7rem] tracking-[0.14em] text-muted-foreground uppercase">
            Section {module.index + 1}
            {read ? " · read" : ""}
          </p>
          <h2 className="font-heading mt-1 text-2xl tracking-tight text-ink">
            {module.title}
          </h2>
        </div>
        <StatusBadge module={module} />
      </header>

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
        <CitedText
          text={body}
          activeId={activeCite}
          onCite={setActiveCite}
          className="font-notes text-[1.1rem] leading-relaxed text-ink/90"
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

      {canMarkRead ? (
        <div className="mt-6">
          <Button type="button" variant="secondary" size="sm" onClick={onMarkRead}>
            Mark as read
          </Button>
        </div>
      ) : null}

      {module.notes?.quiz && !module.notes.refused ? (
        <div className="mt-8">
          <QuizPanel quiz={module.notes.quiz} onCite={setActiveCite} />
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
                      c{chunk.id}
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
              c{activeChunk.id}
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
