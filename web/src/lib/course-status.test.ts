/**
 * What the library says about a course.
 *
 * Most of this is deciding between "still writing", "stopped part way" and
 * "finished", which the reader needs to tell apart before deciding whether to
 * open something. Counts come from several fields that disagree: a course that
 * was cancelled has fewer written sections than planned ones, and progress is
 * only meaningful against the planned count.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  courseLabel,
  isFinishedReading,
  libraryBadge,
  pickContinueCourse,
  plannedCount,
  readCount,
  readingMinutes,
  relativeWhen,
} from "@/lib/course-status";
import type { SavedCourseSummary } from "@/lib/types";

function course(over: Partial<SavedCourseSummary> = {}): SavedCourseSummary {
  return {
    id: 1,
    goal: "teach me q-learning",
    module_count: 4,
    created_at: new Date().toISOString(),
    ...over,
  } as SavedCourseSummary;
}

describe("counting sections", () => {
  it("prefers the planned count over what was written", () => {
    // A course stopped after two of five sections is two of five, not two of
    // two, or the progress bar claims it finished.
    const c = course({ module_count: 2, planned_count: 5 });
    expect(plannedCount(c)).toBe(5);
  });

  it("falls back to the titles, then to what was written", () => {
    expect(plannedCount(course({ module_titles: ["a", "b", "c"] }))).toBe(3);
    expect(plannedCount(course({ module_count: 4 }))).toBe(4);
  });

  it("treats a missing or malformed progress list as nothing read", () => {
    expect(readCount(course())).toBe(0);
    expect(readCount(course({ progress: {} }))).toBe(0);
    expect(
      readCount(course({ progress: { modules_read: null } } as never)),
    ).toBe(0);
  });

  it("is finished only when every planned section is read", () => {
    const partial = course({
      planned_count: 3,
      progress: { modules_read: [0, 1] },
    });
    expect(isFinishedReading(partial)).toBe(false);
    const done = course({
      planned_count: 3,
      progress: { modules_read: [0, 1, 2] },
    });
    expect(isFinishedReading(done)).toBe(true);
  });

  it("is not finished when nothing was planned", () => {
    // Zero of zero is vacuously complete, which would badge an empty course
    // as finished.
    expect(isFinishedReading(course({ module_count: 0 }))).toBe(false);
  });
});

describe("libraryBadge", () => {
  it("reports generation before anything about reading", () => {
    const c = course({
      generation_status: "generating",
      usable_count: 4,
      planned_count: 4,
      progress: { modules_read: [0, 1, 2, 3] },
    });
    expect(libraryBadge(c)).toBe("generating");
  });

  it("distinguishes a partial course from a ready one", () => {
    expect(libraryBadge(course({ generation_status: "partial" }))).toBe(
      "partial",
    );
    expect(libraryBadge(course({ usable_count: 2 }))).toBe("ready");
  });

  it("calls a course with no usable sections empty, not ready", () => {
    // Every section refused: there is nothing to open.
    expect(libraryBadge(course({ usable_count: 0 }))).toBe("empty");
  });

  it("badges a fully read course as finished", () => {
    const c = course({
      usable_count: 3,
      planned_count: 3,
      progress: { modules_read: [0, 1, 2] },
    });
    expect(libraryBadge(c)).toBe("finished");
  });
});

describe("pickContinueCourse", () => {
  it("prefers unfinished work over a finished course listed first", () => {
    const finished = course({
      id: 1,
      usable_count: 2,
      planned_count: 2,
      progress: { modules_read: [0, 1] },
    });
    const unread = course({ id: 2, usable_count: 3, planned_count: 3 });
    expect(pickContinueCourse([finished, unread])?.id).toBe(2);
  });

  it("offers a still-generating course so the reader can watch it", () => {
    const generating = course({ id: 7, generation_status: "generating" });
    expect(pickContinueCourse([generating])?.id).toBe(7);
  });

  it("returns nothing when everything is finished", () => {
    const done = course({
      usable_count: 1,
      planned_count: 1,
      progress: { modules_read: [0] },
    });
    expect(pickContinueCourse([done])).toBeNull();
    expect(pickContinueCourse([])).toBeNull();
  });
});

describe("courseLabel", () => {
  it("prefers the planner's title to the raw goal", () => {
    expect(courseLabel({ title: "Q-learning basics", goal: "algebra-from" })).toBe(
      "Q-learning basics",
    );
  });

  it("falls back to the goal when the title is missing or blank", () => {
    expect(courseLabel({ goal: "teach me algebra" })).toBe("teach me algebra");
    expect(courseLabel({ title: "   ", goal: "teach me algebra" })).toBe(
      "teach me algebra",
    );
  });
});

describe("readingMinutes", () => {
  it("is null when nothing has been written", () => {
    expect(readingMinutes(undefined)).toBeNull();
    expect(readingMinutes(0)).toBeNull();
  });

  it("never rounds a written course down to zero minutes", () => {
    expect(readingMinutes(30)).toBe(1);
  });

  it("reads at 200 words a minute", () => {
    expect(readingMinutes(2000)).toBe(10);
  });
});

describe("relativeWhen", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-31T12:00:00Z"));
  });
  afterEach(() => vi.useRealTimers());

  const ago = (ms: number) =>
    relativeWhen(new Date(Date.now() - ms).toISOString());

  it("says just now for the freshest courses", () => {
    expect(ago(5_000)).toBe("just now");
  });

  it("rounds to the nearest minute rather than flooring", () => {
    // The boundary is 30s, not 60s: 45 seconds ago reads better as "1 min
    // ago" than as "just now".
    expect(ago(29_000)).toBe("just now");
    expect(ago(45_000)).toBe("1 min ago");
  });

  it("counts minutes, then hours, then days", () => {
    expect(ago(5 * 60_000)).toBe("5 min ago");
    expect(ago(3 * 3_600_000)).toBe("3 hours ago");
    expect(ago(2 * 86_400_000)).toBe("2 days ago");
  });

  it("singularises one hour and one day", () => {
    expect(ago(3_600_000)).toBe("1 hour ago");
    expect(ago(86_400_000)).toBe("1 day ago");
  });

  it("falls back to a date beyond a week", () => {
    expect(ago(30 * 86_400_000)).toMatch(/\w+ \d+/);
  });

  it("returns nothing for an unparseable timestamp", () => {
    expect(relativeWhen("not a date")).toBe("");
  });
});
