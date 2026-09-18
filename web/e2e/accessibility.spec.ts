import { expect, test } from "@playwright/test";

/**
 * Guards for the desktop keyboard and screen-reader pass.
 *
 * Every assertion here corresponds to a defect that was actually found and
 * fixed, so a regression fails rather than merely looking different.
 */

// Wide enough for the lg breakpoint, where the sidebar replaces the header.
// The skip link regression these tests exist for was invisible below it.
test.use({ viewport: { width: 1440, height: 900 } });

/**
 * Put the caret at the very start of the document, then Tab.
 *
 * A bare keyboard.press("Tab") immediately after goto() is a race: the
 * document may not hold focus yet, the press goes nowhere and the assertion
 * sees document.body. Focusing body first makes the first stop deterministic.
 */
async function tabFromTop(page: import("@playwright/test").Page) {
  await page.locator("body").press("Tab");
}

test.describe("desktop accessibility", () => {
  test("the skip link is the first stop and moves focus into main", async ({
    page,
  }) => {
    await page.goto("/");

    // It used to live inside a lg:hidden header, so on a desktop it was
    // display:none and the sidebar's whole course library came first.
    const skip = page.getByRole("link", { name: "Skip to content" });
    await tabFromTop(page);
    await expect(skip).toBeFocused();
    await expect(skip).toBeVisible();

    // tabIndex=-1 on <main> is what makes this move focus rather than only
    // scroll. Without it the next Tab would resume from the top of the page.
    await page.keyboard.press("Enter");
    await expect(page.locator("main#main")).toBeFocused();
  });

  test("landmarks are named, and only one main carries the skip target", async ({
    page,
  }) => {
    await page.goto("/");

    // The sidebar announced as an unnamed "complementary".
    await expect(
      page.getByRole("complementary", { name: "Library" }),
    ).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();

    // #main moved to the layout precisely so no page can forget it and no two
    // can declare it at once.
    await expect(page.locator("#main")).toHaveCount(1);
    await expect(page.locator("main")).toHaveCount(1);
    await expect(page.locator("h1")).toHaveCount(1);
  });

  test("a focused control paints a visible ring", async ({ page }) => {
    await page.goto("/");

    // Reached by keyboard, because Chrome does not match :focus-visible for a
    // programmatic focus() and the rule would silently not apply. An audit
    // that used focus() reported all 41 focusable elements as unstyled.
    //
    // Stepped through by name rather than by counting presses, so the
    // assertion cannot pass against whatever happens to be focused if
    // hydration has not finished. The target is the wordmark, which is the
    // ring that was missing: it had no focus-visible utility and fell back to
    // the browser's own 1px auto outline.
    await tabFromTop(page);
    await expect(page.getByRole("link", { name: "Skip to content" })).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(page.getByRole("link", { name: "NoteKit" })).toBeFocused();

    const ring = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      if (!el || el === document.body) return null;
      const style = getComputedStyle(el);
      return {
        label: (el.textContent ?? "").trim().slice(0, 20),
        focusVisible: el.matches(":focus-visible"),
        width: parseFloat(style.outlineWidth),
        style: style.outlineStyle,
      };
    });

    expect(ring).not.toBeNull();
    expect(ring!.focusVisible).toBe(true);
    expect(ring!.style).not.toBe("none");
    expect(ring!.width).toBeGreaterThanOrEqual(2);
  });

  test("an option's name is the option, not its explanation", async ({
    page,
  }) => {
    await page.goto("/");

    // The options start collapsed, which is also why the run-on name went
    // unnoticed for so long.
    await page.getByText("Options", { exact: false }).first().click();

    // The hint used to sit inside the <label>, so the accessible name was a
    // run-on sentence read out ahead of the checkbox's own state.
    const quiz = page.getByRole("checkbox", { name: "Add practice questions" });
    await expect(quiz).toBeVisible();

    const describedBy = await quiz.getAttribute("aria-describedby");
    expect(describedBy).toBeTruthy();
    await expect(page.locator(`#${describedBy}`)).toContainText(
      "questions per section",
    );
  });

  test("the page does not scroll sideways at desktop width", async ({
    page,
  }) => {
    await page.goto("/");
    const overflow = await page.evaluate(
      () => document.body.scrollWidth > window.innerWidth,
    );
    expect(overflow).toBe(false);
  });
});
