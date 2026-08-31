/**
 * Turning a failure into something the reader can act on.
 *
 * Two things matter here beyond the wording. The first is naming the cause:
 * the backend's own message is exact but shaped for a log, and a reader should
 * not have to open a disclosure to learn that their API account is empty.
 *
 * The second is whether retrying can possibly help, which is not the same
 * question. A dropped stream is worth retrying immediately. An empty credit
 * balance is not worth retrying at all until somebody adds credits, and a
 * button offering to try again is then actively misleading: it was clicked
 * twice on a course that could never have succeeded. Those failures name the
 * action instead, and the course page's own Resume control is still there once
 * the action is done.
 */

export type RunErrorGuidance = {
  headline: string;
  next: string;
  /** Whether trying again right now could plausibly succeed. */
  retryable: boolean;
};

export function guidanceFor(message: string): RunErrorGuidance {
  const lower = message.toLowerCase();

  // Checked before the generic 400 and authentication cases, both of which
  // this message would otherwise match.
  if (
    lower.includes("credit balance") ||
    lower.includes("billing") ||
    lower.includes("insufficient_quota") ||
    lower.includes("quota")
  ) {
    return {
      headline: "The Anthropic account is out of credit",
      next: "Nothing here will work until the balance is topped up, at console.anthropic.com under Plans and Billing. Retrying will keep failing.",
      retryable: false,
    };
  }
  if (
    lower.includes("fetch") ||
    lower.includes("networkerror") ||
    lower.includes("failed to fetch")
  ) {
    return {
      headline: "Can't reach the NoteKit service",
      next: "The backend isn't responding. Start it with `uv run uvicorn notekit.api:app --port 8000`, then try again.",
      retryable: true,
    };
  }
  if (lower.includes("database")) {
    return {
      headline: "The database isn't running",
      next: "Start it with `docker compose up -d` from the project folder, then try again.",
      retryable: true,
    };
  }
  if (
    lower.includes("api_key") ||
    lower.includes("authentication") ||
    lower.includes("401")
  ) {
    return {
      headline: "The API key is missing or invalid",
      next: "Check that ANTHROPIC_API_KEY is set in your .env file, then restart the backend.",
      retryable: false,
    };
  }
  if (lower.includes("rate") || lower.includes("429")) {
    return {
      headline: "Too many requests right now",
      next: "The model is rate limiting. Wait a minute and try again.",
      retryable: true,
    };
  }
  if (
    lower.includes("no such") ||
    lower.includes("404") ||
    lower.includes("not found")
  ) {
    return {
      headline: "That isn't there any more",
      next: "It may have been deleted. Go back and pick something else.",
      retryable: false,
    };
  }
  return {
    headline: "Something went wrong",
    next: "The step didn't finish. Trying again usually works; if it keeps failing, the detail below will say why.",
    retryable: true,
  };
}
