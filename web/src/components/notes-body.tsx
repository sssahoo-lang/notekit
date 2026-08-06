"use client";

import dynamic from "next/dynamic";
import { useMemo } from "react";

import { CitedText } from "@/components/cited-text";

const ExcalidrawDiagram = dynamic(
  () =>
    import("@/components/excalidraw-diagram").then((m) => m.ExcalidrawDiagram),
  {
    ssr: false,
    loading: () => (
      <div
        role="status"
        className="flex h-48 items-center justify-center rounded-xl border border-dashed border-border/80 text-sm text-muted-foreground"
      >
        Drawing diagram…
      </div>
    ),
  },
);

type Segment =
  | { type: "prose"; text: string }
  | { type: "diagram"; code: string; caption: string }
  | { type: "pending" };

const FENCE = /```mermaid\s*\n([\s\S]*?)```/gi;

/**
 * Split note body into prose and Mermaid fences. A following caption line
 * (usually carrying [cID] citations) stays with the diagram.
 */
export function splitNotesBody(
  text: string,
  options: { streaming?: boolean } = {},
): Segment[] {
  const streaming = options.streaming ?? false;
  const segments: Segment[] = [];
  let last = 0;
  const matches = [...text.matchAll(FENCE)];

  for (const match of matches) {
    const start = match.index ?? 0;
    if (start > last) {
      const prose = text.slice(last, start).trim();
      if (prose) segments.push({ type: "prose", text: prose });
    }
    const code = (match[1] ?? "").trim();
    const after = text.slice(start + match[0].length);
    const captionMatch = after.match(/^\s*\n?([^\n`]+)/);
    let caption = "";
    let consumed = 0;
    if (captionMatch) {
      const line = captionMatch[1].trim();
      // Captions are short and usually cite sources; avoid eating the next section.
      if (line && line.length < 280 && !line.startsWith("```")) {
        caption = line;
        consumed = captionMatch[0].length;
      }
    }
    if (code) segments.push({ type: "diagram", code, caption });
    last = start + match[0].length + consumed;
  }

  const rest = text.slice(last);
  if (streaming && /```mermaid\b/i.test(rest) && !/```mermaid[\s\S]*```/i.test(rest)) {
    const open = rest.search(/```mermaid\b/i);
    const before = rest.slice(0, open).trim();
    if (before) segments.push({ type: "prose", text: before });
    segments.push({ type: "pending" });
    return segments;
  }

  const prose = rest.trim();
  if (prose) segments.push({ type: "prose", text: prose });
  return segments;
}

type Props = {
  text: string;
  streaming?: boolean;
  activeId?: number | null;
  onCite?: (id: number) => void;
  className?: string;
  numbering?: Map<number, number>;
  hidden?: boolean;
};

/** Cited prose with optional Excalidraw diagrams from Mermaid fences. */
export function NotesBody({
  text,
  streaming = false,
  activeId,
  onCite,
  className,
  numbering,
  hidden = false,
}: Props) {
  const segments = useMemo(
    () => splitNotesBody(text, { streaming }),
    [text, streaming],
  );

  return (
    <div className={className}>
      {segments.map((segment, index) => {
        if (segment.type === "prose") {
          return (
            <CitedText
              key={`p-${index}`}
              text={segment.text}
              activeId={activeId}
              onCite={onCite}
              numbering={numbering}
              hidden={hidden}
            />
          );
        }
        if (segment.type === "pending") {
          return (
            <p
              key={`pending-${index}`}
              role="status"
              className="mt-6 text-sm text-muted-foreground"
            >
              Drawing diagram…
            </p>
          );
        }
        return (
          <figure key={`d-${index}`} className="mt-6 space-y-2">
            <ExcalidrawDiagram definition={segment.code} />
            {segment.caption ? (
              <figcaption>
                <CitedText
                  text={segment.caption}
                  activeId={activeId}
                  onCite={onCite}
                  numbering={numbering}
                  hidden={hidden}
                  className="font-sans text-sm text-muted-foreground"
                />
              </figcaption>
            ) : null}
          </figure>
        );
      })}
    </div>
  );
}
