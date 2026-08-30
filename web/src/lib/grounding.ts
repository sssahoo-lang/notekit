/**
 * How broadly each section is grounded.
 *
 * Faithfulness asks "is every claim supported?" and can answer yes for a
 * section whose every claim comes from one document. That section is fully
 * faithful and still fragile: it inherits whatever that single source got
 * wrong, with nothing to corroborate it. Nothing in the app surfaces that
 * today — the number this measures is breadth, not correctness.
 *
 * Counted from the citation markers in the prose rather than from the
 * retrieved chunk list, because retrieval hands the model far more passages
 * than it ends up using. What matters is what the writing actually leaned on.
 */

import type { ModuleState } from "./types";

const CITATION = /\[c(\d+)\]/g;

/** At or below this many distinct documents, a section has no corroboration. */
export const NARROW_SOURCE_LIMIT = 2;

/**
 * Below this many citations a section is simply short, and calling it
 * "narrow" would be noise rather than a finding.
 */
export const MIN_CITATIONS_TO_FLAG = 4;

export type SectionGrounding = {
  index: number;
  title: string;
  /** Distinct documents the prose actually cites. */
  sources: number;
  /** Citation markers that resolve to a passage we hold. */
  citations: number;
  /** Many claims, few documents — worth a second look. */
  narrow: boolean;
  refused: boolean;
  /** Distinct document titles, most-cited first. */
  documents: string[];
};

export function sectionGrounding(module: ModuleState): SectionGrounding {
  const notes = module.notes;
  const base = {
    index: module.index,
    title: module.title,
    refused: Boolean(notes?.refused),
  };

  if (!notes || notes.refused || !notes.body) {
    return { ...base, sources: 0, citations: 0, narrow: false, documents: [] };
  }

  const byId = new Map(notes.chunks.map((c) => [c.id, c]));
  const perDocument = new Map<string, number>();
  let citations = 0;

  for (const match of notes.body.matchAll(CITATION)) {
    const chunk = byId.get(Number(match[1]));
    // A marker we cannot resolve is not evidence of anything, so it does not
    // count toward breadth either.
    if (!chunk) continue;
    citations += 1;
    const title = chunk.document_title || "Untitled source";
    perDocument.set(title, (perDocument.get(title) ?? 0) + 1);
  }

  const documents = [...perDocument.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([title]) => title);

  return {
    ...base,
    sources: documents.length,
    citations,
    narrow:
      documents.length > 0 &&
      documents.length <= NARROW_SOURCE_LIMIT &&
      citations >= MIN_CITATIONS_TO_FLAG,
    documents,
  };
}

export function courseGrounding(modules: ModuleState[]): SectionGrounding[] {
  return modules.map(sectionGrounding);
}

/** Whether the map has anything to say yet. */
export function hasGrounding(rows: SectionGrounding[]): boolean {
  return rows.some((r) => r.citations > 0);
}
