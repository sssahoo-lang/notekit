/**
 * Classifying a failure.
 *
 * The case that prompted these: a course failed with an empty credit balance,
 * and the card said "Trying again usually works" above a button that could
 * never work. It was clicked twice. So the tests care about two things per
 * error, what it is called and whether retrying is offered, and the billing
 * string is pinned to the exact message the Anthropic API actually returns
 * rather than one paraphrased from memory.
 */

import { describe, expect, it } from "vitest";

import { guidanceFor } from "@/lib/run-error";

// Captured verbatim from a live 400, via str(exc) on the backend.
const OUT_OF_CREDIT =
  "Error code: 400 - {'type': 'error', 'error': {'type': " +
  "'invalid_request_error', 'message': 'Your credit balance is too low to " +
  "access the Anthropic API. Please go to Plans & Billing to upgrade or " +
  "purchase credits.'}, 'request_id': 'req_011CebQZPkL3jz276itNpZZW'}";

describe("an empty credit balance", () => {
  it("is named rather than left to the disclosure", () => {
    const g = guidanceFor(OUT_OF_CREDIT);
    expect(g.headline).toMatch(/credit/i);
    expect(g.next).toMatch(/console\.anthropic\.com/);
  });

  it("does not offer a retry, because retrying cannot work", () => {
    expect(guidanceFor(OUT_OF_CREDIT).retryable).toBe(false);
  });

  it("never falls through to the generic advice", () => {
    // The regression: this message reached the default branch and claimed
    // that trying again usually works.
    expect(guidanceFor(OUT_OF_CREDIT).next).not.toMatch(/usually works/i);
  });

  it("wins over the 400 that the same message also contains", () => {
    // Ordering matters: the raw text carries "400", and a generic HTTP branch
    // placed first would swallow it.
    expect(guidanceFor(OUT_OF_CREDIT).headline).not.toMatch(
      /something went wrong/i,
    );
  });
});

describe("what is worth retrying", () => {
  const retryable = [
    ["a dropped connection", "TypeError: Failed to fetch"],
    ["a stopped database", "database connection refused"],
    ["rate limiting", "Error code: 429 rate_limit_error"],
    ["anything unrecognised", "Unexpected token < in JSON"],
  ] as const;

  const terminal = [
    ["no credit", OUT_OF_CREDIT],
    ["a bad key", "authentication_error: invalid x-api-key"],
    ["a deleted course", "course 16 not found"],
  ] as const;

  it.each(retryable)("offers a retry for %s", (_label, message) => {
    expect(guidanceFor(message).retryable).toBe(true);
  });

  it.each(terminal)("withholds the retry for %s", (_label, message) => {
    expect(guidanceFor(message).retryable).toBe(false);
  });
});

describe("every branch", () => {
  const messages = [
    OUT_OF_CREDIT,
    "Failed to fetch",
    "database is not running",
    "authentication_error",
    "429 rate limited",
    "not found",
    "something unrecognised entirely",
  ];

  it("says what happened and what to do next", () => {
    for (const message of messages) {
      const g = guidanceFor(message);
      expect(g.headline.length).toBeGreaterThan(0);
      expect(g.next.length).toBeGreaterThan(0);
    }
  });

  it("names an action whenever it withholds the retry", () => {
    // A dead end with no way forward is worse than the wrong advice.
    for (const message of messages) {
      const g = guidanceFor(message);
      if (!g.retryable) {
        expect(g.next).toMatch(/console\.anthropic\.com|\.env|Go back/i);
      }
    }
  });
});
