import { defineConfig, devices } from "@playwright/test";

/**
 * Browser checks for the things a unit test cannot see.
 *
 * vitest.config.ts explains why components are not rendered into jsdom: a
 * copy of them would test the mock. The same reasoning points here for
 * anything about focus, tab order or a computed accessible name. Chrome only
 * matches :focus-visible for input it considers keyboard-driven, so a
 * programmatic .focus() cannot exercise the rule these tests exist to guard -
 * an earlier audit reported all 41 focusable elements as unstyled for exactly
 * that reason, and was wrong.
 *
 * Offline like the rest of CI. The API is not started, the site gate renders
 * its children when it cannot reach one, and no assertion here depends on a
 * course, a corpus or a model call.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: "http://127.0.0.1:3100",
    trace: "on-first-retry",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
  webServer: {
    // The production build, not the dev server: the dev overlay injects its
    // own focusable elements and would sit in the middle of tab order.
    //
    // CI has already run the build as its own step, so building again here
    // would cost a minute to produce the same output. Locally there may be no
    // build yet, so one is made.
    command: process.env.CI
      ? "npm run start -- --port 3100"
      : "npm run build && npm run start -- --port 3100",
    url: "http://127.0.0.1:3100",
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
  },
});
