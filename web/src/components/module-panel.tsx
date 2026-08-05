"use client";

import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { ModuleState } from "@/lib/types";
import { cn } from "@/lib/utils";

import { CitedText } from "./cited-text";
import { QuizPanel } from "./quiz-panel";

type Props = {
  module: ModuleState;
};

export function ModulePanel({ module }: Props) {
  const [activeCite, setActiveCite] = useState<number | null>(null);
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

  return (
    <article
      className={cn(
        "animate-in fade-in slide-in-from-bottom-2 duration-500",
        "rounded-2xl border border-border/70 bg-paper px-5 py-6 shadow-sm sm:px-8 sm:py-8",
      )}
    >
      <header className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-mono text-[0.7rem] tracking-[0.14em] text-muted-foreground uppercase">
            Module {module.index + 1}
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
          className="font-notes text-[1.05rem] text-ink/90"
        />
      ) : null}

      {module.status === "streaming" && !body ? (
        <p className="text-sm text-muted-foreground">Retrieving sources…</p>
      ) : null}

      {module.status === "streaming" && body ? (
        <span className="mt-2 inline-block h-4 w-1.5 animate-pulse bg-primary/70 align-middle" />
      ) : null}

      {module.notes && !module.notes.refused ? (
        <>
          <Separator className="my-7" />
          <Tabs defaultValue={module.notes.quiz ? "quiz" : "sources"}>
            <TabsList>
              {module.notes.quiz ? (
                <TabsTrigger value="quiz">Quiz</TabsTrigger>
              ) : null}
              <TabsTrigger value="sources">
                Sources ({chunkList.length})
              </TabsTrigger>
            </TabsList>
            {module.notes.quiz ? (
              <TabsContent value="quiz" className="mt-5">
                <QuizPanel quiz={module.notes.quiz} onCite={setActiveCite} />
              </TabsContent>
            ) : null}
            <TabsContent value="sources" className="mt-5 space-y-3">
              {chunkList.length === 0 ? (
                <p className="text-sm text-muted-foreground">No passages.</p>
              ) : (
                chunkList.map((chunk) => (
                  <button
                    key={chunk.id}
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
                      <span className="font-mono text-xs text-muted-foreground">
                        score {chunk.score.toFixed(2)}
                      </span>
                    </div>
                    <p className="line-clamp-3 text-sm text-muted-foreground">
                      {chunk.text}
                    </p>
                  </button>
                ))
              )}
            </TabsContent>
          </Tabs>
        </>
      ) : null}

      {activeChunk ? (
        <aside className="mt-6 rounded-xl border border-cite/30 bg-cite/8 px-4 py-3">
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
          Refused
        </Badge>
      );
    case "error":
      return <Badge variant="destructive">Error</Badge>;
    case "done":
      return <Badge variant="secondary">Done</Badge>;
  }
}
