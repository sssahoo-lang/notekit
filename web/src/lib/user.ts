const USER_KEY = "notekit.user";

export function getStoredUser(): string {
  if (typeof window === "undefined") return "";
  return localStorage.getItem(USER_KEY) ?? "";
}

export function setStoredUser(user: string): void {
  if (typeof window === "undefined") return;
  const trimmed = user.trim();
  if (trimmed) localStorage.setItem(USER_KEY, trimmed);
  else localStorage.removeItem(USER_KEY);
}
