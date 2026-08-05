"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { getHealth } from "@/lib/api";
import { getProfile, setDisplayName, type Profile } from "@/lib/profile";
import { cn } from "@/lib/utils";

const LINKS = [
  { href: "/", label: "Study" },
  { href: "/upload", label: "Materials" },
  { href: "/style", label: "Style" },
];

export function SiteHeader() {
  const pathname = usePathname();
  const [ok, setOk] = useState<boolean | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");

  useEffect(() => {
    setProfile(getProfile());
    let cancelled = false;
    getHealth()
      .then(() => !cancelled && setOk(true))
      .catch(() => !cancelled && setOk(false));
    return () => {
      cancelled = true;
    };
  }, []);

  function save() {
    setProfile(setDisplayName(draft));
    setEditing(false);
  }

  return (
    <header className="sticky top-0 z-40 border-b border-border/70 bg-background/90 backdrop-blur-md">
      <a
        href="#main"
        className="sr-only rounded-md bg-primary px-3 py-2 text-primary-foreground focus:not-sr-only focus:absolute focus:top-2 focus:left-2"
      >
        Skip to content
      </a>

      <div className="mx-auto flex h-14 max-w-5xl items-center justify-between gap-2 px-3 sm:gap-4 sm:px-6">
        <Link
          href="/"
          className="font-heading text-lg tracking-tight text-ink transition-colors hover:text-primary"
        >
          NoteKit
        </Link>

        <nav aria-label="Main" className="flex min-w-0 items-center gap-0.5">
          {LINKS.map((link) => {
            const active =
              link.href === "/"
                ? pathname === "/"
                : pathname.startsWith(link.href);
            return (
              <Link
                key={link.href}
                href={link.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "rounded-md px-2.5 py-1.5 text-sm transition-colors",
                  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
                  active
                    ? "bg-primary/10 font-medium text-primary"
                    : "text-foreground/65 hover:bg-muted hover:text-foreground",
                )}
              >
                {link.label}
              </Link>
            );
          })}

          <span className="mx-1.5 h-4 w-px bg-border" aria-hidden="true" />

          {editing ? (
            <span className="flex items-center gap-1.5">
              <Label htmlFor="display-name" className="sr-only">
                Your name
              </Label>
              <Input
                id="display-name"
                autoFocus
                value={draft}
                placeholder="Your name"
                className="h-8 w-28 text-sm"
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") save();
                  if (e.key === "Escape") setEditing(false);
                }}
              />
              <Button type="button" size="sm" className="h-8" onClick={save}>
                Save
              </Button>
            </span>
          ) : (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="max-w-[7rem] truncate text-foreground/60"
              onClick={() => {
                setDraft(profile?.name ?? "");
                setEditing(true);
              }}
            >
              {profile?.name?.trim() || "Name"}
            </Button>
          )}

          <span
            role="status"
            className={cn(
              "ml-1 hidden items-center gap-1.5 rounded-md border px-2 py-0.5 text-[0.7rem] sm:inline-flex",
              ok === true && "border-teal-800/20 bg-teal-50/80 text-teal-900",
              ok === false &&
                "border-destructive/40 bg-destructive/5 text-destructive",
              ok === null && "border-border text-muted-foreground",
            )}
          >
            <span
              aria-hidden="true"
              className={cn(
                "size-1.5 rounded-full",
                ok === true && "bg-teal-700",
                ok === false && "bg-destructive",
                ok === null && "animate-pulse bg-muted-foreground",
              )}
            />
            <span className="sr-only sm:not-sr-only">
              {ok === true ? "Connected" : ok === false ? "Offline" : "…"}
            </span>
          </span>
        </nav>
      </div>

      {ok === false ? (
        <p
          role="alert"
          className="border-t border-destructive/25 bg-destructive/5 px-4 py-2 text-center text-sm text-destructive"
        >
          Can&apos;t reach the NoteKit service. Start it with{" "}
          <code className="font-mono text-xs">
            uv run uvicorn notekit.api:app --reload --reload-dir src --port 8000
          </code>
        </p>
      ) : null}
    </header>
  );
}
