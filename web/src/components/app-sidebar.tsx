"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { getHealth, listCourses } from "@/lib/api";
import { courseLabel } from "@/lib/course-status";
import { useCourseNav } from "@/lib/course-nav";
import { getProfile, setDisplayName, type Profile } from "@/lib/profile";
import type { SavedCourseSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

const LINKS = [
  { href: "/", label: "Study" },
  { href: "/upload", label: "Materials" },
  { href: "/style", label: "Style" },
];

function readCount(c: SavedCourseSummary): number {
  return Array.isArray(c.progress?.modules_read)
    ? c.progress!.modules_read!.length
    : 0;
}

/**
 * The desktop shell: navigation and library, always on screen.
 *
 * The app was one centred column about 800px wide, which on a 1600px monitor
 * used half the screen and read as a phone app. Width is better spent on
 * structure than on longer lines — prose still wants roughly 68 characters, so
 * the reading column stays narrow and the space around it carries the things
 * you navigate by.
 */
export function AppSidebar() {
  const pathname = usePathname();
  const nav = useCourseNav();
  const [profile, setProfile] = useState<Profile | null>(null);
  const [courses, setCourses] = useState<SavedCourseSummary[]>([]);
  const [ok, setOk] = useState<boolean | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");

  useEffect(() => {
    // See upload-workspace.tsx: getProfile() must run post-hydration, not in
    // a lazy initializer, or the server's "anonymous" stub and the client's
    // real profile disagree on first paint.
    const p = getProfile();
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setProfile(p);
    getHealth()
      .then(() => setOk(true))
      .catch(() => setOk(false));
  }, []);

  useEffect(() => {
    if (!profile) return;
    let cancelled = false;
    listCourses(profile.id)
      .then((rows) => !cancelled && setCourses(rows))
      .catch(() => !cancelled && setCourses([]));
    return () => {
      cancelled = true;
    };
  }, [profile, nav.refreshToken]);

  function save() {
    setProfile(setDisplayName(draft));
    setEditing(false);
  }

  return (
    <aside className="hidden w-60 shrink-0 flex-col border-r border-border/70 bg-sidebar/60 lg:flex xl:w-64">
      <div className="flex h-14 items-center px-5">
        <Link
          href="/"
          onClick={() => nav.goHome()}
          className="font-heading text-lg tracking-tight text-ink transition-colors hover:text-primary"
        >
          NoteKit
        </Link>
      </div>

      <nav aria-label="Main" className="px-3">
        <ul className="space-y-0.5">
          {LINKS.map((link) => {
            const active =
              link.href === "/"
                ? pathname === "/"
                : pathname.startsWith(link.href);
            return (
              <li key={link.href}>
                <Link
                  href={link.href}
                  aria-current={active ? "page" : undefined}
                  onClick={() => link.href === "/" && nav.goHome()}
                  className={cn(
                    "block rounded-md px-3 py-1.5 text-sm transition-colors",
                    "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
                    active
                      ? "bg-primary/10 font-medium text-primary"
                      : "text-foreground/70 hover:bg-muted hover:text-foreground",
                  )}
                >
                  {link.label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      <div className="mt-6 min-h-0 flex-1 overflow-y-auto px-3 pb-4">
        <p className="px-3 font-mono text-[0.65rem] tracking-[0.14em] text-muted-foreground uppercase">
          Your courses
        </p>

        {courses.length === 0 ? (
          <p className="mt-2 px-3 text-sm text-muted-foreground">
            Courses you build appear here.
          </p>
        ) : (
          <ul className="mt-2 space-y-0.5">
            {courses.map((course) => {
              const read = readCount(course);
              const done = course.module_count > 0 && read >= course.module_count;
              return (
                <li key={course.id}>
                  <button
                    type="button"
                    onClick={() => nav.requestOpen(course.id)}
                    className={cn(
                      "block w-full rounded-md px-3 py-2 text-left transition-colors",
                      "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
                      "hover:bg-muted",
                    )}
                  >
                    <span className="line-clamp-2 text-sm leading-snug text-foreground/85">
                      {courseLabel(course)}
                    </span>
                    <span className="mt-0.5 block text-xs text-muted-foreground">
                      {done
                        ? "Finished"
                        : read > 0
                          ? `${read} of ${course.module_count} read`
                          : `${course.module_count} sections`}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <div className="border-t border-border/70 p-3">
        <div className="mb-1 flex justify-end">
          <ThemeToggle className="text-muted-foreground hover:text-foreground" />
        </div>
        {editing ? (
          <div className="flex items-center gap-1.5">
            <Label htmlFor="sidebar-name" className="sr-only">
              Your name
            </Label>
            <Input
              id="sidebar-name"
              autoFocus
              value={draft}
              placeholder="Your name"
              className="h-8 text-sm"
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") save();
                if (e.key === "Escape") setEditing(false);
              }}
            />
            <Button type="button" size="sm" className="h-8" onClick={save}>
              Save
            </Button>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => {
              setDraft(profile?.name ?? "");
              setEditing(true);
            }}
            className="flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left hover:bg-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          >
            <span className="truncate text-sm text-foreground/80">
              {profile?.name?.trim() || "Add your name"}
            </span>
            <span
              aria-hidden="true"
              className={cn(
                "size-1.5 shrink-0 rounded-full",
                ok === true && "bg-primary",
                ok === false && "bg-destructive",
                ok === null && "animate-pulse bg-muted-foreground",
              )}
            />
          </button>
        )}
        <p className="sr-only" role="status">
          {ok === false ? "NoteKit service unreachable" : ""}
        </p>
      </div>
    </aside>
  );
}
