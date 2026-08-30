"use client";

import { ProgressBar } from "@/components/progress-bar";
import type { ModuleState } from "@/lib/types";
import { cn } from "@/lib/utils";
import { scrollToSection } from "@/lib/go-to-section";

/**
 * Where you are in a long course, and how to get somewhere else.
 *
 * A course runs to about twenty screens of scrolling. Before this, every
 * navigation control lived at the top of the page and scrolled away, so a
 * reader four screens down had no way to tell which section they were in, jump
 * to another, or get back — the classic orientation failure in long documents.
 *
 * Desktop gets a persistent rail of section titles. Narrow screens, where a
 * rail would eat the reading column, get a compact sticky bar naming the
 * current section instead. Numbers alone were not enough: "3" tells you
 * nothing about what section three contains.
 */

type Props = {
  modules: ModuleState[];
  activeIndex: number;
  readIndices: number[];
  onSelect: (index: number) => void;
};

function goTo(index: number, onSelect: (i: number) => void) {
  onSelect(index);
  scrollToSection(index);
}

export function SectionRail({
  modules,
  activeIndex,
  readIndices,
  onSelect,
}: Props) {
  if (modules.length < 2) return null;

  const current = modules.find((m) => m.index === activeIndex) ?? modules[0];
  const readCount = readIndices.length;

  return (
    <>
      {/* Narrow screens: one line saying where you are, plus progress. */}
      <div className="sticky top-14 z-30 -mx-4 mb-6 border-b border-border/70 bg-background/90 px-4 py-2.5 backdrop-blur-md lg:hidden">
        <details className="group">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-3 [&::-webkit-details-marker]:hidden">
            <span className="min-w-0">
              <span className="font-mono text-[0.65rem] tracking-[0.12em] text-muted-foreground uppercase">
                Section {current.index + 1} of {modules.length}
              </span>
              <span className="block truncate text-sm font-medium text-ink">
                {current.title}
              </span>
            </span>
            <span className="shrink-0 text-xs text-muted-foreground group-open:hidden">
              All sections
            </span>
            <span className="hidden shrink-0 text-xs text-muted-foreground group-open:inline">
              Close
            </span>
          </summary>

          <ol className="mt-2 space-y-0.5 pb-1">
            {modules.map((m) => (
              <li key={m.index}>
                <button
                  type="button"
                  onClick={() => goTo(m.index, onSelect)}
                  className={cn(
                    "flex w-full items-baseline gap-2 rounded-md px-2 py-1.5 text-left text-sm",
                    "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
                    m.index === activeIndex
                      ? "bg-primary/10 font-medium text-primary"
                      : "text-foreground/75 hover:bg-muted",
                  )}
                >
                  <span className="font-mono text-xs text-muted-foreground">
                    {m.index + 1}
                  </span>
                  <span className="min-w-0 flex-1 truncate">{m.title}</span>
                  {readIndices.includes(m.index) ? (
                    <span className="shrink-0 text-xs text-muted-foreground">
                      read
                    </span>
                  ) : null}
                </button>
              </li>
            ))}
          </ol>
        </details>

        <ProgressBar
          className="mt-2 h-1"
          value={readCount}
          max={modules.length}
          label={`${readCount} of ${modules.length} sections read`}
        />
      </div>

      {/* Wide screens: a rail that stays put. */}
      <nav
        aria-label="Sections"
        className="hidden lg:sticky lg:top-24 lg:block lg:self-start"
      >
        <p className="font-mono text-[0.65rem] tracking-[0.14em] text-muted-foreground uppercase">
          {readCount} of {modules.length} read
        </p>
        <ol className="mt-3 space-y-0.5 border-l border-border">
          {modules.map((m) => {
            const active = m.index === activeIndex;
            const read = readIndices.includes(m.index);
            return (
              <li key={m.index}>
                <button
                  type="button"
                  onClick={() => goTo(m.index, onSelect)}
                  aria-current={active ? "true" : undefined}
                  className={cn(
                    "-ml-px block w-full border-l-2 py-1.5 pl-3 text-left text-sm leading-snug transition-colors",
                    "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
                    active
                      ? "border-primary font-medium text-primary"
                      : read
                        ? "border-primary/30 text-foreground/60 hover:text-foreground"
                        : "border-transparent text-foreground/70 hover:border-border-strong hover:text-foreground",
                  )}
                >
                  <span className="font-mono text-[0.7rem] text-muted-foreground">
                    {m.index + 1}
                  </span>{" "}
                  {m.title}
                </button>
              </li>
            );
          })}
        </ol>
      </nav>
    </>
  );
}
