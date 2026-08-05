"use client";

import { useMemo } from "react";

import { cn } from "@/lib/utils";

const CITATION = /\[c(\d+)\]/g;

type Props = {
  text: string;
  activeId?: number | null;
  onCite?: (id: number) => void;
  className?: string;
};

/** Render note body with clickable [c123] citation markers. */
export function CitedText({ text, activeId, onCite, className }: Props) {
  const parts = useMemo(() => {
    const out: Array<string | { id: number }> = [];
    let last = 0;
    for (const match of text.matchAll(CITATION)) {
      const start = match.index ?? 0;
      if (start > last) out.push(text.slice(last, start));
      out.push({ id: Number(match[1]) });
      last = start + match[0].length;
    }
    if (last < text.length) out.push(text.slice(last));
    return out;
  }, [text]);

  return (
    <div className={cn("whitespace-pre-wrap leading-relaxed", className)}>
      {parts.map((part, i) => {
        if (typeof part === "string") {
          return <span key={i}>{part}</span>;
        }
        const active = activeId === part.id;
        return (
          <button
            key={`${part.id}-${i}`}
            type="button"
            onClick={() => onCite?.(part.id)}
            className={cn(
              "mx-0.5 inline-flex translate-y-[-1px] items-center rounded-sm px-1 py-0.5 font-mono text-[0.7rem] font-medium transition-colors",
              active
                ? "bg-cite text-cite-foreground"
                : "bg-cite/15 text-cite-foreground hover:bg-cite/25",
            )}
          >
            c{part.id}
          </button>
        );
      })}
    </div>
  );
}
