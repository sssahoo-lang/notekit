"use client";

import {
  courseGrounding,
  hasGrounding,
  NARROW_SOURCE_LIMIT,
  type SectionGrounding,
} from "@/lib/grounding";
import type { ModuleState } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * How broadly each section is sourced, as one glance.
 *
 * Deliberately the only dark surface in the app. Everything else sits within a
 * few points of the same pale tone, so a reader has nothing to anchor on; this
 * panel is a different kind of thing — analysis rather than reading — and the
 * tonal shift says so without a heading having to.
 *
 * Bars are sized by distinct documents, not by citation count. A section can
 * carry twelve citations and still rest on two sources, and that is exactly
 * the case worth seeing.
 */

type Props = {
  modules: ModuleState[];
  activeSection: number;
  onSelectSection: (index: number) => void;
};

function Bar({
  row,
  max,
  active,
  onSelect,
}: {
  row: SectionGrounding;
  max: number;
  active: boolean;
  onSelect: () => void;
}) {
  // A floor so a one-source section is still a visible target, not a sliver.
  const height = row.sources > 0 ? Math.max(18, (row.sources / max) * 100) : 6;

  return (
    <button
      type="button"
      onClick={onSelect}
      aria-label={
        row.refused
          ? `Section ${row.index + 1}, ${row.title}, refused for lack of sources`
          : `Section ${row.index + 1}, ${row.title}, ${row.sources} source${
              row.sources === 1 ? "" : "s"
            }`
      }
      className="group flex min-w-0 flex-1 flex-col justify-end gap-0 text-left focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-teal-300/70"
    >
      <div className="flex h-[132px] items-end">
        <div
          style={{ height: `${height}%` }}
          className={cn(
            "w-full rounded-t-md transition-all duration-300 motion-reduce:transition-none",
            row.refused
              ? "bg-slate-600/40"
              : row.narrow
                ? "bg-gradient-to-b from-[#8E3B37] to-[#5E2A2A] group-hover:from-[#a04642]"
                : "bg-gradient-to-b from-[#2E6F6B] to-[#1E4F50] group-hover:from-[#37827d]",
            active && "ring-2 ring-teal-300/70 ring-offset-2 ring-offset-[#15212A]",
          )}
        />
      </div>

      <div className="mt-3 border-t border-white/10 pt-3">
        <div className="font-mono text-[10px] tracking-[0.14em] text-slate-400">
          {String(row.index + 1).padStart(2, "0")}
        </div>
        <div className="mt-1 line-clamp-2 text-[13px] leading-snug text-slate-100">
          {row.title}
        </div>
        <div
          className={cn(
            "mt-1.5 text-[11.5px]",
            row.refused
              ? "text-slate-400"
              : row.narrow
                ? "text-[#E0837C]"
                : "text-teal-300/90",
          )}
        >
          {row.refused
            ? "refused"
            : row.sources === 0
              ? "—"
              : `${row.sources} source${row.sources === 1 ? "" : "s"}`}
        </div>
      </div>
    </button>
  );
}

export function CourseMap({ modules, activeSection, onSelectSection }: Props) {
  const rows = courseGrounding(modules);
  if (!hasGrounding(rows)) return null;

  const max = Math.max(...rows.map((r) => r.sources), 1);
  const narrow = rows.filter((r) => r.narrow);

  return (
    <section
      aria-label="Course map"
      className="overflow-hidden rounded-2xl bg-[#15212A] p-6 sm:p-8"
    >
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="font-mono text-[10.5px] tracking-[0.2em] text-teal-300/80 uppercase">
            Course map
          </div>
          <h2 className="mt-2 font-heading text-2xl tracking-tight text-slate-50 sm:text-[28px]">
            {narrow.length ? "Where the evidence is thin" : "How this course is sourced"}
          </h2>
        </div>
        <p className="max-w-[38ch] text-[13px] leading-relaxed text-slate-400 sm:text-right">
          Each section sized by how many separate documents it cites — breadth,
          not correctness.
        </p>
      </div>

      <div className="mt-8 flex items-end gap-3 sm:gap-5">
        {rows.map((row) => (
          <Bar
            key={row.index}
            row={row}
            max={max}
            active={row.index === activeSection}
            onSelect={() => onSelectSection(row.index)}
          />
        ))}
      </div>

      <div className="mt-7 border-t border-white/10 pt-5 text-[13px] leading-relaxed text-slate-400">
        {narrow.length ? (
          <>
            <span className="text-slate-200">
              {narrow.length === 1
                ? `Section ${narrow[0].index + 1} draws every claim from ${
                    narrow[0].sources === 1 ? "one document" : `${narrow[0].sources} documents`
                  }.`
                : `${narrow.length} sections rest on ${NARROW_SOURCE_LIMIT} documents or fewer.`}
            </span>{" "}
            Every claim there is still cited — there is just nothing else
            corroborating it.
          </>
        ) : (
          <>No section leans on fewer than {NARROW_SOURCE_LIMIT + 1} documents.</>
        )}
      </div>
    </section>
  );
}
