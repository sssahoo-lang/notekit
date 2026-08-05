"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { getHealth } from "@/lib/api";
import { cn } from "@/lib/utils";

const LINKS = [
  { href: "/", label: "Course" },
  { href: "/upload", label: "Upload" },
  { href: "/style", label: "Style" },
];

export function SiteHeader() {
  const pathname = usePathname();
  const [ok, setOk] = useState<boolean | null>(null);

  useEffect(() => {
    let cancelled = false;
    getHealth()
      .then(() => {
        if (!cancelled) setOk(true);
      })
      .catch(() => {
        if (!cancelled) setOk(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <header className="relative z-10 border-b border-border/60 bg-background/70 backdrop-blur-md">
      <div className="mx-auto flex h-14 max-w-5xl items-center justify-between gap-4 px-4 sm:px-6">
        <Link href="/" className="group flex items-baseline gap-2">
          <span className="font-heading text-xl tracking-tight text-ink transition-colors group-hover:text-primary">
            NoteKit
          </span>
        </Link>
        <nav className="flex items-center gap-1 sm:gap-2">
          {LINKS.map((link) => {
            const active =
              link.href === "/"
                ? pathname === "/"
                : pathname.startsWith(link.href);
            return (
              <Link
                key={link.href}
                href={link.href}
                className={cn(
                  "rounded-md px-2.5 py-1.5 text-sm transition-colors",
                  active
                    ? "bg-primary/8 font-medium text-primary"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {link.label}
              </Link>
            );
          })}
          <span
            className={cn(
              "ml-2 inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 font-mono text-[0.65rem] tracking-wide uppercase",
              ok === true && "border-teal-700/20 bg-teal-50 text-teal-900",
              ok === false && "border-destructive/30 bg-destructive/5 text-destructive",
              ok === null && "border-border text-muted-foreground",
            )}
            title={
              ok === true
                ? "API connected"
                : ok === false
                  ? "API unreachable — start uvicorn on :8000"
                  : "Checking API…"
            }
          >
            <span
              className={cn(
                "size-1.5 rounded-full",
                ok === true && "bg-teal-600",
                ok === false && "bg-destructive",
                ok === null && "animate-pulse bg-muted-foreground",
              )}
            />
            {ok === true ? "API" : ok === false ? "Offline" : "…"}
          </span>
        </nav>
      </div>
    </header>
  );
}
