"use client";

import { useMemo } from "react";

import { cn } from "@/lib/utils";

const CITATION = /\[c(\d+)\]/g;

type Props = {
  text: string;
  activeId?: number | null;
  onCite?: (id: number) => void;
  className?: string;
  /**
   * Chunk id to its position among this section's sources. Raw ids like c2751
   * carry no meaning for a reader and are wide; "1" and "2" read like footnotes.
   */
  numbering?: Map<number, number>;
  /** Hide markers entirely for uninterrupted reading. Sources stay listed. */
  hidden?: boolean;
};

type Token = string | { ids: number[] };

/** Split on blank lines so each paragraph is a real element. */
function toParagraphs(text: string): string[] {
  return text.split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean);
}

/**
 * Note body with its citations.
 *
 * Citations are the point of this project, but at roughly four markers per
 * hundred words they were interrupting the line more often than a comma. Three
 * things keep them checkable without taxing the reading: they are numbered per
 * section rather than by raw chunk id, drawn as superscripts rather than filled
 * chips, and consecutive markers are merged. The model frequently emits
 * [c1291][c1327] for one claim, which rendered as two separate blocks.
 */
export function CitedText({
  text,
  activeId,
  onCite,
  className,
  numbering,
  hidden = false,
}: Props) {
  const paragraphs = useMemo(() => toParagraphs(text), [text]);

  return (
    <div className={cn(className)}>
      {paragraphs.map((paragraph, index) => (
        <Paragraph
          key={index}
          index={index}
          text={paragraph}
          activeId={activeId}
          onCite={onCite}
          numbering={numbering}
          hidden={hidden}
        />
      ))}
    </div>
  );
}

function Paragraph({
  index,
  text,
  activeId,
  onCite,
  numbering,
  hidden,
}: {
  index: number;
  text: string;
  activeId?: number | null;
  onCite?: (id: number) => void;
  numbering?: Map<number, number>;
  hidden: boolean;
}) {
  const tokens = useMemo(() => {
    const raw: Token[] = [];
    let last = 0;
    for (const match of text.matchAll(CITATION)) {
      const start = match.index ?? 0;
      if (start > last) raw.push(text.slice(last, start));
      raw.push({ ids: [Number(match[1])] });
      last = start + match[0].length;
    }
    if (last < text.length) raw.push(text.slice(last));

    // Merge runs of markers separated by nothing but whitespace.
    const merged: Token[] = [];
    for (const token of raw) {
      const prev = merged[merged.length - 1];
      if (typeof token !== "string") {
        if (prev && typeof prev !== "string") {
          for (const id of token.ids) if (!prev.ids.includes(id)) prev.ids.push(id);
          continue;
        }
        const beforePrev = merged[merged.length - 2];
        if (
          typeof prev === "string" &&
          prev.trim() === "" &&
          beforePrev &&
          typeof beforePrev !== "string"
        ) {
          merged.pop();
          for (const id of token.ids)
            if (!beforePrev.ids.includes(id)) beforePrev.ids.push(id);
          continue;
        }
      }
      merged.push(typeof token === "string" ? token : { ids: [...token.ids] });
    }
    return merged;
  }, [text]);

  return (
    <p data-paragraph={index} className="mt-4 first:mt-0">
      {tokens.map((token, i) => {
        if (typeof token === "string") {
          // Markers sat after a space ("word [c1]"), which left a gap once they
          // became superscripts. Tuck them against the word they support.
          const next = tokens[i + 1];
          const trimmable = !hidden && next && typeof next !== "string";
          return (
            <span key={i}>{trimmable ? token.replace(/ $/, "") : token}</span>
          );
        }
        if (hidden) return null;

        const active = token.ids.includes(activeId ?? -1);
        const labels = token.ids.map((id) => numbering?.get(id) ?? id);

        return (
          <sup key={`${token.ids.join("-")}-${i}`} className="ml-px">
            {token.ids.map((id, j) => (
              <span key={id}>
                {j > 0 ? <span className="text-cite/60">,</span> : null}
                <button
                  type="button"
                  onClick={() => onCite?.(id)}
                  aria-label={`Source ${labels[j]}`}
                  className={cn(
                    "rounded-[3px] px-[3px] text-[0.68em] font-medium transition-colors duration-150",
                    "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-ring",
                    active
                      ? "bg-cite text-cite-foreground"
                      : "text-cite-foreground/70 hover:bg-cite/20 hover:text-cite-foreground",
                  )}
                >
                  {labels[j]}
                </button>
              </span>
            ))}
          </sup>
        );
      })}
    </p>
  );
}
