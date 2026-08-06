"use client";

import {
  convertToExcalidrawElements,
  Excalidraw,
} from "@excalidraw/excalidraw";
import { parseMermaidToExcalidraw } from "@excalidraw/mermaid-to-excalidraw";
import { useEffect, useState } from "react";

import { cn } from "@/lib/utils";

import "@excalidraw/excalidraw/index.css";

type Props = {
  definition: string;
  className?: string;
};

type DiagramElements = ReturnType<typeof convertToExcalidrawElements>;

/**
 * Mermaid → Excalidraw sketch. Generation stays Mermaid (reliable for the
 * model and easy to ground); display uses Excalidraw's hand-drawn look.
 */
export function ExcalidrawDiagram({ definition, className }: Props) {
  const [elements, setElements] = useState<DiagramElements | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setBusy(true);
    setError(null);
    setElements(null);

    void (async () => {
      try {
        const { elements: skeleton } = await parseMermaidToExcalidraw(
          definition.trim(),
          {
            flowchart: { curve: "basis" },
            themeVariables: { fontSize: "16px" },
          },
        );
        const full = convertToExcalidrawElements(skeleton);
        if (cancelled) return;
        setElements(full);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Could not draw diagram");
      } finally {
        if (!cancelled) setBusy(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [definition]);

  if (error) {
    return (
      <pre
        className={cn(
          "overflow-x-auto rounded-xl border border-border/70 bg-muted/40 p-4 font-mono text-xs text-muted-foreground",
          className,
        )}
      >
        {definition.trim()}
      </pre>
    );
  }

  if (busy || !elements) {
    return (
      <div
        role="status"
        className={cn(
          "flex h-48 items-center justify-center rounded-xl border border-dashed border-border/80 bg-card/60 text-sm text-muted-foreground",
          className,
        )}
      >
        Drawing diagram…
      </div>
    );
  }

  return (
    <div
      className={cn(
        "h-72 overflow-hidden rounded-xl border border-border/70 bg-[#fafaf9] shadow-[inset_0_1px_0_oklch(0.95_0.01_95)] sm:h-80",
        className,
      )}
    >
      <Excalidraw
        key={definition}
        initialData={{
          elements,
          appState: {
            viewBackgroundColor: "#fafaf9",
            zenModeEnabled: true,
          },
          scrollToContent: true,
        }}
        viewModeEnabled
        zenModeEnabled
        gridModeEnabled={false}
        UIOptions={{
          canvasActions: {
            changeViewBackgroundColor: false,
            clearCanvas: false,
            export: false,
            loadScene: false,
            saveToActiveFile: false,
            toggleTheme: false,
            saveAsImage: false,
          },
        }}
      />
    </div>
  );
}
