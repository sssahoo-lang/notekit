/**
 * Breadth of grounding, which is a different question from faithfulness.
 *
 * The measurement that matters is "how many distinct documents did the prose
 * actually lean on", and the two easy ways to get it wrong are counting the
 * retrieved chunks (retrieval hands the model far more than it uses) and
 * counting citation markers (one document cited six times is still one
 * document). These pin down both.
 */

import { describe, expect, it } from "vitest";

import {
  MIN_CITATIONS_TO_FLAG,
  NARROW_SOURCE_LIMIT,
  courseGrounding,
  hasGrounding,
  sectionGrounding,
} from "@/lib/grounding";
import type { ModuleState } from "@/lib/types";

function chunk(id: number, documentTitle: string) {
  return {
    id,
    citation_key: `c${id}`,
    text: "passage text",
    document_title: documentTitle,
    document_url: "https://example.org",
    score: 1,
  };
}

function sectionWith(
  body: string,
  chunks: ReturnType<typeof chunk>[],
  extra: Partial<ModuleState> = {},
): ModuleState {
  return {
    index: 0,
    title: "A section",
    ...extra,
    notes: { body, chunks, refused: false, ...(extra.notes ?? {}) },
  } as ModuleState;
}

describe("sectionGrounding", () => {
  it("counts distinct documents, not citation markers", () => {
    const section = sectionWith("A [c1]. B [c2]. C [c1].", [
      chunk(1, "Sutton and Barto"),
      chunk(2, "Watkins"),
    ]);
    const result = sectionGrounding(section);
    expect(result.citations).toBe(3);
    expect(result.sources).toBe(2);
  });

  it("ignores retrieved passages the prose never cited", () => {
    // Retrieval supplies far more than generation uses. Counting what was
    // fetched would report breadth the writing does not have.
    const section = sectionWith("Only one [c1].", [
      chunk(1, "Sutton and Barto"),
      chunk(2, "Never cited"),
      chunk(3, "Also never cited"),
    ]);
    expect(sectionGrounding(section).sources).toBe(1);
  });

  it("drops a marker that resolves to no passage we hold", () => {
    // A hallucinated or slimmed-away id is not evidence of anything.
    const section = sectionWith("Real [c1], bogus [c9999].", [
      chunk(1, "Sutton and Barto"),
    ]);
    const result = sectionGrounding(section);
    expect(result.citations).toBe(1);
    expect(result.documents).toEqual(["Sutton and Barto"]);
  });

  it("orders documents by how often each is cited", () => {
    const section = sectionWith("[c1] [c2] [c2] [c3] [c2] [c1]", [
      chunk(1, "Twice"),
      chunk(2, "Thrice"),
      chunk(3, "Once"),
    ]);
    expect(sectionGrounding(section).documents).toEqual([
      "Thrice",
      "Twice",
      "Once",
    ]);
  });

  it("names a source with no title rather than dropping it", () => {
    const section = sectionWith("A [c1].", [chunk(1, "")]);
    expect(sectionGrounding(section).documents).toEqual(["Untitled source"]);
  });

  describe("the narrow flag", () => {
    function withCitations(count: number, documents: number) {
      const chunks = Array.from({ length: documents }, (_, i) =>
        chunk(i + 1, `Doc ${i + 1}`),
      );
      // Spread the citations round-robin so every document is used.
      const body = Array.from(
        { length: count },
        (_, i) => `[c${(i % documents) + 1}]`,
      ).join(" ");
      return sectionGrounding(sectionWith(body, chunks));
    }

    it("flags many claims resting on few documents", () => {
      expect(withCitations(MIN_CITATIONS_TO_FLAG, NARROW_SOURCE_LIMIT).narrow).toBe(
        true,
      );
    });

    it("does not flag a section that is merely short", () => {
      // Below the citation floor "narrow" would be noise, not a finding.
      expect(
        withCitations(MIN_CITATIONS_TO_FLAG - 1, NARROW_SOURCE_LIMIT).narrow,
      ).toBe(false);
    });

    it("does not flag a section drawing on enough documents", () => {
      expect(
        withCitations(MIN_CITATIONS_TO_FLAG + 4, NARROW_SOURCE_LIMIT + 1).narrow,
      ).toBe(false);
    });

    it("never flags a section with no citations at all", () => {
      const section = sectionWith("No markers here.", [chunk(1, "Unused")]);
      const result = sectionGrounding(section);
      expect(result.sources).toBe(0);
      expect(result.narrow).toBe(false);
    });
  });

  it("reports a refusal as refused rather than as narrow", () => {
    const section = {
      index: 1,
      title: "Refused section",
      notes: { body: "", chunks: [], refused: true },
    } as unknown as ModuleState;
    const result = sectionGrounding(section);
    expect(result.refused).toBe(true);
    expect(result.narrow).toBe(false);
    expect(result.sources).toBe(0);
  });

  it("handles a section that has not been written yet", () => {
    const section = { index: 2, title: "Pending" } as ModuleState;
    expect(sectionGrounding(section).citations).toBe(0);
  });
});

describe("courseGrounding and hasGrounding", () => {
  it("keeps one row per section, in order", () => {
    const rows = courseGrounding([
      sectionWith("A [c1].", [chunk(1, "One")], { index: 0, title: "First" }),
      sectionWith("B [c2].", [chunk(2, "Two")], { index: 1, title: "Second" }),
    ]);
    expect(rows.map((r) => r.title)).toEqual(["First", "Second"]);
  });

  it("says there is nothing to show until something is cited", () => {
    // The map should stay hidden while a course is still streaming.
    expect(hasGrounding(courseGrounding([]))).toBe(false);
    const uncited = courseGrounding([sectionWith("No markers.", [])]);
    expect(hasGrounding(uncited)).toBe(false);
    const cited = courseGrounding([sectionWith("A [c1].", [chunk(1, "One")])]);
    expect(hasGrounding(cited)).toBe(true);
  });
});
