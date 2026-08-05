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

// Labels name what the reader does, not what the backend calls it.
const LINKS = [
  { href: "/", label: "Study" },
  { href: "/upload", label: "Your material" },
  { href: "/style", label: "Writing style" },
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
    <header className="relative z-10 border-b border-border bg-background/80 backdrop-blur-md">
      <a
        href="#main"
        className="sr-only rounded-md bg-primary px-3 py-2 text-primary-foreground focus:not-sr-only focus:absolute focus:top-2 focus:left-2"
      >
        Skip to content
      </a>

      <div className="mx-auto flex h-16 max-w-5xl items-center justify-between gap-4 px-4 sm:px-6">
        <Link href="/" className="group flex items-baseline gap-2">
          <span className="font-heading text-xl tracking-tight text-ink transition-colors group-hover:text-primary">
            NoteKit
          </span>
        </Link>

        <nav aria-label="Main" className="flex items-center gap-1">
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
                  "rounded-md px-3 py-2 text-sm transition-colors",
                  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
                  active
                    ? "bg-primary/10 font-medium text-primary"
                    : "text-foreground/70 hover:bg-muted hover:text-foreground",
                )}
              >
                {link.label}
              </Link>
            );
          })}

          <span className="mx-1 h-5 w-px bg-border" aria-hidden="true" />

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
                className="h-8 w-32 text-sm"
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
              className="text-foreground/70"
              onClick={() => {
                setDraft(profile?.name ?? "");
                setEditing(true);
              }}
            >
              {profile?.name?.trim() || "Add your name"}
            </Button>
          )}

          <span
            role="status"
            className={cn(
              "ml-1 inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs",
              ok === true && "border-teal-800/25 bg-teal-50 text-teal-900",
              ok === false && "border-destructive/40 bg-destructive/5 text-destructive",
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
            {ok === true ? "Connected" : ok === false ? "Offline" : "Checking"}
          </span>
        </nav>
      </div>

      {ok === false ? (
        <p
          role="alert"
          className="border-t border-destructive/25 bg-destructive/5 px-4 py-2 text-center text-sm text-destructive"
        >
          Can&apos;t reach the NoteKit service. Start it with{" "}
          <code className="font-mono">
            uv run uvicorn notekit.api:app --port 8000
          </code>
        </p>
      ) : null}
    </header>
  );
}
