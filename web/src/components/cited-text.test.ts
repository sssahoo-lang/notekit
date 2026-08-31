/**
 * Splitting a note body into paragraphs.
 *
 * A generated section came back as one unbroken wall of text. The model had
 * written a bulleted list, separating items with single newlines, and the
 * split was on blank lines only, so every item ran into the next. The notes
 * task tells the model not to use lists; it does anyway, and the reader should
 * not pay for that.
 */

import { describe, expect, it } from "vitest";

import { toParagraphs } from "@/components/cited-text";

describe("toParagraphs", () => {
  it("splits on blank lines, as before", () => {
    expect(toParagraphs("One.\n\nTwo.")).toEqual(["One.", "Two."]);
  });

  it("keeps a soft-wrapped sentence in one piece", () => {
    // Single newlines inside prose are wrapping, not structure.
    expect(toParagraphs("A sentence that\nwrapped across lines.")).toEqual([
      "A sentence that\nwrapped across lines.",
    ]);
  });

  it("gives each list item its own paragraph", () => {
    // The exact shape that rendered as run-together text.
    const body =
      "- Relational databases model data as rows [c1].\n" +
      "- Object databases appeared in the 1980s [c2].\n" +
      "- In the 2000s, NoSQL arrived [c3].";
    expect(toParagraphs(body)).toHaveLength(3);
  });

  it("handles the other list markers and numbering", () => {
    expect(toParagraphs("* one\n* two")).toHaveLength(2);
    expect(toParagraphs("1. one\n2. two")).toHaveLength(2);
    expect(toParagraphs("1) one\n2) two")).toHaveLength(2);
  });

  it("separates a bolded lead-in from the list under it", () => {
    const body =
      "**Learning goal 1 - Compare databases**\n" +
      "- Relational databases use tables [c1].\n" +
      "- NoSQL relaxes that [c2].";
    const paragraphs = toParagraphs(body);
    expect(paragraphs).toHaveLength(3);
    expect(paragraphs[0]).toContain("Learning goal 1");
  });

  it("does not strand a leading blank or produce empty paragraphs", () => {
    expect(toParagraphs("\n\n- one\n- two\n\n")).toEqual(["- one", "- two"]);
    expect(toParagraphs("")).toEqual([]);
    expect(toParagraphs("   \n  \n ")).toEqual([]);
  });

  it("leaves a hyphen inside a sentence alone", () => {
    // Only a line that opens like a list item counts as one.
    const body = "Costs fell 30-40 percent [c1].\nThat trend held [c2].";
    expect(toParagraphs(body)).toEqual([body]);
  });
});
