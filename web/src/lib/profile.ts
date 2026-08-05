/**
 * Who this browser is, without asking anyone to type an identity.
 *
 * The browser holds one stable id and an optional display name; the id is the
 * only thing sent to the API. Cleared localStorage used to mint a brand-new
 * `reader-…` id and hide every saved course — we keep a durable list of ids
 * this browser has ever used so those courses can be claimed back.
 */

const KEY = "notekit.profile";
const LEGACY_KEY = "notekit.user";
const IDS_KEY = "notekit.profile.ids";

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

function rememberedIds(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(IDS_KEY);
    const parsed = raw ? (JSON.parse(raw) as unknown) : [];
    return Array.isArray(parsed)
      ? parsed.filter((x): x is string => typeof x === "string" && !!x)
      : [];
  } catch {
    return [];
  }
}

function rememberId(id: string): void {
  if (typeof window === "undefined" || !id) return;
  const ids = rememberedIds();
  if (ids.includes(id)) return;
  localStorage.setItem(IDS_KEY, JSON.stringify([...ids, id]));
}

/** Every id this browser has used, plus the normalised display name if set. */
export function claimAliases(profile: Profile): string[] {
  const aliases = new Set<string>(rememberedIds());
  aliases.add(profile.id);
  if (profile.name.trim()) aliases.add(normalizeId(profile.name));
  aliases.delete(profile.id);
  return [...aliases];
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
      if (parsed.id) {
        rememberId(parsed.id);
        return { id: parsed.id, name: parsed.name ?? "" };
      }
    } catch {
      // Corrupt entry: fall through and mint a fresh profile rather than
      // leaving the reader stuck on a broken one.
    }
  }

  const legacy = localStorage.getItem(LEGACY_KEY)?.trim();
  const known = rememberedIds();
  // Prefer a previously used id over minting a new empty one.
  const profile: Profile =
    legacy
      ? { id: normalizeId(legacy), name: legacy }
      : known.length
        ? { id: known[0], name: "" }
        : { id: createId(), name: "" };

  localStorage.setItem(KEY, JSON.stringify(profile));
  rememberId(profile.id);
  if (legacy) localStorage.removeItem(LEGACY_KEY);
  return profile;
}

export function setDisplayName(name: string): Profile {
  const current = getProfile();
  const next: Profile = { ...current, name: name.trim() };
  if (typeof window !== "undefined") {
    localStorage.setItem(KEY, JSON.stringify(next));
    rememberId(next.id);
    if (next.name) rememberId(normalizeId(next.name));
  }
  return next;
}

/** First name, or a neutral fallback. Used for greetings only. */
export function greetingName(profile: Profile): string {
  const first = profile.name.trim().split(/\s+/)[0];
  return first || "there";
}
