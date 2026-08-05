/**
 * Who this browser is, without asking anyone to type an identity.
 *
 * The old model was a free-text "user id" field matched exactly, so a capital
 * letter or a stray space silently gave you a different, empty history. Now the
 * browser holds one stable id and an optional display name, and the id is the
 * only thing sent to the API.
 */

const KEY = "notekit.profile";
const LEGACY_KEY = "notekit.user";

export type Profile = {
  /** Stable storage key. Never shown; never typed. */
  id: string;
  /** What the reader calls themselves. Cosmetic only. */
  name: string;
};

/** Mirrors identity.normalize on the backend so ids agree on both sides. */
export function normalizeId(value: string): string {
  const key = value
    .trim()
    .toLowerCase()
    .replace(/[\s._]+/g, "-")
    .replace(/[^a-z0-9-]/g, "")
    .replace(/-{2,}/g, "-")
    .replace(/^-|-$/g, "");
  return key || "anonymous";
}

function createId(): string {
  const random =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID().slice(0, 8)
      : Math.random().toString(36).slice(2, 10);
  return `reader-${random}`;
}

/**
 * The profile for this browser, creating one on first visit.
 *
 * If an old free-text user id is present, it is adopted rather than discarded:
 * its normalised form becomes the id, which keeps any material already uploaded
 * under that name reachable.
 */
export function getProfile(): Profile {
  if (typeof window === "undefined") return { id: "anonymous", name: "" };

  const stored = localStorage.getItem(KEY);
  if (stored) {
    try {
      const parsed = JSON.parse(stored) as Partial<Profile>;
      if (parsed.id) return { id: parsed.id, name: parsed.name ?? "" };
    } catch {
      // Corrupt entry: fall through and mint a fresh profile rather than
      // leaving the reader stuck on a broken one.
    }
  }

  const legacy = localStorage.getItem(LEGACY_KEY)?.trim();
  const profile: Profile = legacy
    ? { id: normalizeId(legacy), name: legacy }
    : { id: createId(), name: "" };

  localStorage.setItem(KEY, JSON.stringify(profile));
  if (legacy) localStorage.removeItem(LEGACY_KEY);
  return profile;
}

export function setDisplayName(name: string): Profile {
  const current = getProfile();
  const next: Profile = { ...current, name: name.trim() };
  if (typeof window !== "undefined") {
    localStorage.setItem(KEY, JSON.stringify(next));
  }
  return next;
}

/** First name, or a neutral fallback. Used for greetings only. */
export function greetingName(profile: Profile): string {
  const first = profile.name.trim().split(/\s+/)[0];
  return first || "there";
}
