"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { ContinueCard } from "@/components/continue-card";
import { LibraryList } from "@/components/library-list";
import { ModulePanel } from "@/components/module-panel";
import { RunError, RunStatus, type RunPhase } from "@/components/run-status";
import { SectionRail } from "@/components/section-rail";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  cancelCourse,
  claimCourses,
  deleteCourse,
  getCourse,
  getNamespaces,
  getStyle,
  listCourses,
  resumeCourse,
  saveProgress,
  streamCourse,
} from "@/lib/api";
import {
  generationStatus,
  pickContinueCourse,
} from "@/lib/course-status";
import { useCourseNav } from "@/lib/course-nav";
import {
  claimAliases,
  getProfile,
  greetingName,
  type Profile,
} from "@/lib/profile";
import type {
  CourseEvent,
  ModuleState,
  NamespaceInfo,
  SavedCourse,
  SavedCourseSummary,
} from "@/lib/types";

const AUTO_SOURCE = "__auto__";

/** Uploaded corpora that belong to this reader. */
function myUploads(sources: NamespaceInfo[], userId: string): NamespaceInfo[] {
  const prefix = `user-${userId}-`;
  return sources.filter((ns) => ns.namespace.startsWith(prefix));
}

function mapSavedModules(course: SavedCourse): ModuleState[] {
  const titles = course.module_titles ?? [];
  const byIndex = new Map(course.modules.map((m) => [m.index, m]));
  const count = Math.max(titles.length, course.modules.length);

  return Array.from({ length: count }, (_, index) => {
    const m = byIndex.get(index);
    const title = m?.title || titles[index] || `Section ${index + 1}`;
    if (!m) {
      return {
        index,
        title,
        streamingText: "",
        notes: null,
        error: null,
        status: "pending" as const,
      };
    }
    return {
      index: m.index,
      title,
      streamingText: m.notes?.body ?? "",
      notes: m.notes,
      error: m.error,
      status: (m.error
        ? "error"
        : m.notes?.refused
          ? "refused"
          : m.notes?.body
            ? "done"
            : "pending") as ModuleState["status"],
    };
  });
}

function applyCourseEvent(
  event: CourseEvent,
  setters: {
    setPhase: (p: RunPhase | ((prev: RunPhase) => RunPhase)) => void;
    setDetail: (d: string) => void;
    setSummary: (s: string | null) => void;
    setModules: (
      next: ModuleState[] | ((prev: ModuleState[]) => ModuleState[]),
    ) => void;
    setCost: (c: number | null) => void;
    setError: (e: string | null) => void;
    setActiveCourseId: (id: number | null) => void;
  },
): void {
  switch (event.type) {
    case "planning":
      setters.setPhase("planning");
      break;
    case "syllabus":
      setters.setSummary(event.summary);
      setters.setModules(
        event.modules.map((title, index) => ({
          index,
          title,
          streamingText: "",
          notes: null,
          error: null,
          status: "pending",
        })),
      );
      setters.setPhase("writing");
      break;
    case "ingesting":
      setters.setPhase("gathering");
      break;
    case "ingested":
      setters.setDetail(
        event.cached
          ? "Reusing sources gathered earlier."
          : `Read ${event.chunks} passages.`,
      );
      setters.setPhase("writing");
      break;
    case "module_start":
      setters.setPhase("writing");
      break;
    case "token":
      setters.setModules((prev) =>
        prev.map((m) =>
          m.index === event.index
            ? {
                ...m,
                streamingText: m.streamingText + event.text,
                status: "streaming",
              }
            : m,
        ),
      );
      break;
    case "module":
      setters.setModules((prev) =>
        prev.map((m) =>
          m.index === event.index
            ? {
                ...m,
                notes: event.notes,
                streamingText: event.notes.body || m.streamingText,
                status: event.notes.refused ? "refused" : "done",
              }
            : m,
        ),
      );
      break;
    case "module_error":
      setters.setModules((prev) =>
        prev.map((m) =>
          m.index === event.index
            ? { ...m, error: event.error, status: "error" }
            : m,
        ),
      );
      break;
    case "done":
      setters.setCost(event.estimated_cost_usd);
      setters.setPhase("done");
      break;
    case "cancelled":
      setters.setPhase("done");
      break;
    case "saved":
      setters.setActiveCourseId(event.id);
      break;
    case "error":
      setters.setError(event.error);
      setters.setPhase("error");
      break;
  }
}

export function CourseWorkspace() {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [goal, setGoal] = useState("");
  const [sourceMode, setSourceMode] = useState<string>(AUTO_SOURCE);
  const [uploadNs, setUploadNs] = useState<string | null>(null);
  const [sources, setSources] = useState<NamespaceInfo[]>([]);
  const [library, setLibrary] = useState<SavedCourseSummary[]>([]);
  const [activeCourseId, setActiveCourseId] = useState<number | null>(null);
  const [withQuiz, setWithQuiz] = useState(true);
  const [useStyle, setUseStyle] = useState(false);
  const [hasStyle, setHasStyle] = useState(false);
  const [phase, setPhase] = useState<RunPhase>("idle");
  const [detail, setDetail] = useState("");
  const [summary, setSummary] = useState<string | null>(null);
  const [modules, setModules] = useState<ModuleState[]>([]);
  const [cost, setCost] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadingLibrary, setLoadingLibrary] = useState(true);
  const [generatedHere, setGeneratedHere] = useState(false);
  const [courseStatus, setCourseStatus] = useState<
    "generating" | "complete" | "partial" | null
  >(null);
  const [modulesRead, setModulesRead] = useState<number[]>([]);
  const [activeSection, setActiveSection] = useState(0);
  const abortRef = useRef<AbortController | null>(null);
  const titleRef = useRef<HTMLHeadingElement>(null);
  const nav = useCourseNav();

  const userId = profile?.id ?? "anonymous";
  const uploads = useMemo(
    () => (profile ? myUploads(sources, profile.id) : []),
    [sources, profile],
  );

  // The sidebar owns navigation now: it asks for a course, this answers.
  useEffect(() => {
    if (nav.requestedCourseId == null) return;
    const id = nav.requestedCourseId;
    nav.clearRequest();
    void openCourse(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nav.requestedCourseId]);

  useEffect(() => {
    if (nav.homeToken === 0) return;
    resetView();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nav.homeToken]);

  const refreshLibrary = useCallback(async (p: Profile) => {
    try {
      const aliases = claimAliases(p);
      const libraryRows = aliases.length
        ? await claimCourses(p.id, aliases)
        : await listCourses(p.id);
      setLibrary(libraryRows);
      nav.refreshLibrary();
      return libraryRows;
    } catch {
      setLibrary([]);
      return [] as SavedCourseSummary[];
    } finally {
      setLoadingLibrary(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    Promise.resolve().then(() => {
      if (cancelled) return;
      const p = getProfile();
      setProfile(p);
      void refreshLibrary(p);
      getNamespaces()
        .then((rows) => {
          if (!cancelled) setSources(rows);
        })
        .catch(() => {
          if (!cancelled) setSources([]);
        });
      getStyle(p.id)
        .then((s) => {
          if (!cancelled) setHasStyle(!!s);
        })
        .catch(() => {
          if (!cancelled) setHasStyle(false);
        });
    });
    return () => {
      cancelled = true;
    };
  }, [refreshLibrary]);

  // Soft-refresh history while any course is generating in the background.
  useEffect(() => {
    const anyGenerating = library.some(
      (c) => generationStatus(c) === "generating",
    );
    if (!anyGenerating || !profile) return;
    const id = window.setInterval(() => {
      void refreshLibrary(profile);
    }, 4000);
    return () => window.clearInterval(id);
  }, [library, profile, refreshLibrary]);

  // Poll open course while server is still generating.
  useEffect(() => {
    if (!activeCourseId || courseStatus !== "generating") return;
    if (phase === "planning" || phase === "gathering" || phase === "writing") {
      return;
    }
    const id = window.setInterval(() => {
      void getCourse(activeCourseId)
        .then((course) => {
          setModules(mapSavedModules(course));
          setCourseStatus(course.generation_status ?? "complete");
          setSummary(course.summary);
          if (course.estimated_cost_usd != null) {
            setCost(course.estimated_cost_usd);
          }
          if (profile) void refreshLibrary(profile);
        })
        .catch(() => undefined);
    }, 3000);
    return () => window.clearInterval(id);
  }, [activeCourseId, courseStatus, phase, profile, refreshLibrary]);

  const running =
    phase === "planning" || phase === "gathering" || phase === "writing";
  const viewingCourse = modules.length > 0 || activeCourseId != null;

  const modulesDone = useMemo(
    () =>
      modules.filter((m) => ["done", "refused", "error"].includes(m.status))
        .length,
    [modules],
  );

  const continueCourse = useMemo(
    () => pickContinueCourse(library),
    [library],
  );

  function resetView() {
    // Leaving the reader does not cancel generation — it keeps going server-side.
    abortRef.current?.abort();
    abortRef.current = null;
    setActiveCourseId(null);
    setPhase("idle");
    setDetail("");
    setSummary(null);
    setModules([]);
    setCost(null);
    setError(null);
    setGeneratedHere(false);
    setCourseStatus(null);
    setModulesRead([]);
    setActiveSection(0);
  }

  async function persistProgress(
    courseId: number,
    read: number[],
    bookmarkIndex: number,
  ) {
    try {
      await saveProgress(courseId, {
        modules_read: read,
        bookmark: { module_index: bookmarkIndex },
      });
      if (profile) void refreshLibrary(profile);
    } catch {
      // Progress is best-effort; reading still works offline of this write.
    }
  }

  async function markRead(index: number) {
    if (activeCourseId == null) return;
    const next = Array.from(new Set([...modulesRead, index])).sort(
      (a, b) => a - b,
    );
    setModulesRead(next);
    await persistProgress(activeCourseId, next, index);
  }

  async function openCourse(id: number) {
    setError(null);
    abortRef.current?.abort();
    try {
      const course = await getCourse(id);
      const mapped = mapSavedModules(course);
      const read = course.progress?.modules_read ?? [];
      const bookmark = course.progress?.bookmark?.module_index ?? 0;

      setActiveCourseId(course.id);
      setGoal(course.goal);
      setSummary(course.summary);
      setCost(course.estimated_cost_usd);
      setModules(mapped);
      setModulesRead(Array.isArray(read) ? read : []);
      setActiveSection(
        typeof bookmark === "number" && bookmark < mapped.length ? bookmark : 0,
      );
      setCourseStatus(course.generation_status ?? "complete");
      setGeneratedHere(false);
      setPhase(
        course.generation_status === "generating" ? "writing" : "done",
      );
      setDetail(
        course.generation_status === "generating"
          ? "Writing continues in the background."
          : "",
      );
      requestAnimationFrame(() => titleRef.current?.focus());
      if (profile) void refreshLibrary(profile);

      // If still generating, attach to the live stream if a job is running.
      if (course.generation_status === "generating") {
        void attachResume(course.id, false);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function removeCourse(id: number) {
    try {
      await deleteCourse(id, userId);
      if (id === activeCourseId) resetView();
      if (profile) void refreshLibrary(profile);
      toast.success("Course deleted");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  // If the uploaded material backing the current choice goes away, fall back to
  // finding sources. Otherwise the selector hides while still pointing at a
  // namespace the reader can no longer see or change.
  useEffect(() => {
    if (sourceMode === AUTO_SOURCE) return;
    if (!uploads.some((ns) => ns.namespace === sourceMode)) {
      setSourceMode(AUTO_SOURCE);
      setUploadNs(null);
    }
  }, [uploads, sourceMode]);

  function pickSourceMode(value: string | null) {
    if (!value) return;
    if (value === AUTO_SOURCE) {
      setSourceMode(AUTO_SOURCE);
      setUploadNs(null);
      return;
    }
    setSourceMode(value);
    setUploadNs(value);
  }

  const eventSetters = {
    setPhase,
    setDetail,
    setSummary,
    setModules,
    setCost,
    setError,
    setActiveCourseId,
  };

  async function consumeStream(
    events: AsyncGenerator<CourseEvent>,
  ): Promise<void> {
    for await (const event of events) {
      applyCourseEvent(event, eventSetters);
      if (event.type === "saved" && profile) {
        void refreshLibrary(profile);
        setCourseStatus("generating");
      }
      if (event.type === "done") {
        setCourseStatus("complete");
        getNamespaces().then(setSources).catch(() => undefined);
        if (profile) void refreshLibrary(profile);
      }
      if (event.type === "cancelled") {
        setCourseStatus("partial");
        if (profile) void refreshLibrary(profile);
      }
    }
  }

  async function attachResume(id: number, force: boolean) {
    const controller = new AbortController();
    abortRef.current = controller;
    if (force) {
      setPhase("writing");
      setCourseStatus("generating");
      setGeneratedHere(true);
      setError(null);
    }
    try {
      await consumeStream(resumeCourse(id, controller.signal));
      setPhase((p) => (p === "error" ? p : "done"));
    } catch (err) {
      if ((err as Error).name === "AbortError") return;
      // Resume attach can 404/fail if job already finished — refresh instead.
      try {
        const course = await getCourse(id);
        setModules(mapSavedModules(course));
        setCourseStatus(course.generation_status ?? "complete");
        setPhase("done");
      } catch {
        setError(err instanceof Error ? err.message : String(err));
        setPhase("error");
      }
    }
  }

  async function start() {
    if (!goal.trim() || running) return;
    if (sourceMode !== AUTO_SOURCE && !uploadNs) {
      toast.error("Choose your materials, or add some under Materials");
      return;
    }

    const controller = new AbortController();
    abortRef.current = controller;

    setError(null);
    setActiveCourseId(null);
    setModules([]);
    setModulesRead([]);
    setSummary(null);
    setCost(null);
    setPhase("planning");
    setDetail("");
    setGeneratedHere(true);
    setCourseStatus("generating");
    setActiveSection(0);

    try {
      await consumeStream(
        streamCourse(
          {
            goal: goal.trim(),
            user: userId,
            use_style: useStyle && hasStyle,
            with_quiz: withQuiz,
            namespace: sourceMode === AUTO_SOURCE ? null : uploadNs,
          },
          controller.signal,
        ),
      );
      setPhase((p) => (p === "error" ? p : "done"));
    } catch (err) {
      if ((err as Error).name === "AbortError") {
        // Client left the stream; generation may still be running server-side.
        setPhase((p) => (p === "planning" ? "idle" : "done"));
        return;
      }
      setError(err instanceof Error ? err.message : String(err));
      setPhase("error");
      setCourseStatus("partial");
    }
  }

  async function stopGeneration() {
    if (activeCourseId != null) {
      try {
        await cancelCourse(activeCourseId);
      } catch {
        // Still abort the local stream.
      }
      setCourseStatus("partial");
    }
    abortRef.current?.abort();
    setPhase("done");
    if (profile) void refreshLibrary(profile);
    toast.message("Generation stopped — what’s ready is saved");
  }

  async function resumeGeneration() {
    if (activeCourseId == null) return;
    await attachResume(activeCourseId, true);
  }

  const showHome = !running && !viewingCourse;

  return (
    <div
      id="main"
      className={
        showHome
          ? "mx-auto w-full max-w-6xl px-4 py-10 sm:px-6"
          : "mx-auto w-full max-w-5xl px-4 py-10 sm:px-6"
      }
    >
      {showHome ? (
        <div className="lg:grid lg:grid-cols-[minmax(0,1fr)_22rem] lg:gap-12">
          <div className="min-w-0">
          <h1 className="font-heading text-3xl tracking-tight text-ink">
            {profile?.name
              ? `Welcome back, ${greetingName(profile)}`
              : "What do you want to learn?"}
          </h1>
          <p className="mt-2 max-w-prose text-muted-foreground">
            Study notes from real sources, with every claim cited. If the
            sources don&apos;t cover something, NoteKit says so instead of
            guessing.
          </p>

          {!loadingLibrary && continueCourse ? (
            <div className="mt-10">
              <ContinueCard course={continueCourse} onOpen={openCourse} />
            </div>
          ) : null}

          <section aria-labelledby="new-heading" className="mt-10">
            <h2 id="new-heading" className="text-lg font-medium text-ink">
              Start a course
            </h2>

            <div className="mt-4 space-y-5 rounded-2xl border border-border/80 bg-card/90 p-5 shadow-[0_1px_0_oklch(0.9_0.01_220)] sm:p-6">
              <div>
                <Label htmlFor="goal" className="text-sm font-medium">
                  What should this course teach you?
                </Label>
                <Textarea
                  id="goal"
                  value={goal}
                  onChange={(e) => setGoal(e.target.value)}
                  rows={3}
                  className="mt-2 text-base"
                  placeholder="e.g. Teach me Q-learning at an intermediate level"
                  aria-describedby="goal-help"
                />
                <p
                  id="goal-help"
                  className="mt-1.5 text-sm text-muted-foreground"
                >
                  Be specific about the level — it changes how the notes are
                  written. Every goal is saved to History.
                </p>
              </div>

              {/* With nothing uploaded there is only one possible answer, so
                  the control is noise in front of the primary action. It
                  appears once there is a real choice to make. */}
              {uploads.length > 0 ? (
                <div>
                  <Label htmlFor="source" className="text-sm font-medium">
                    Where should the notes come from?
                  </Label>
                  <Select value={sourceMode} onValueChange={pickSourceMode}>
                    <SelectTrigger id="source" className="mt-2">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={AUTO_SOURCE}>
                        Find sources for me
                      </SelectItem>
                      {uploads.map((ns) => (
                        <SelectItem key={ns.namespace} value={ns.namespace}>
                          My material: {ns.namespace.replace(`user-${userId}-`, "")} (
                          {ns.documents} file{ns.documents === 1 ? "" : "s"})
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <p className="mt-1.5 text-sm text-muted-foreground">
                    {sourceMode === AUTO_SOURCE
                      ? "Wikipedia and arXiv for this topic."
                      : "Notes will be written only from your own files."}
                  </p>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">
                  Sources come from Wikipedia and arXiv. To study from your own
                  PDFs instead, add them under{" "}
                  <Link
                    href="/upload"
                    className="font-medium text-primary underline-offset-4 hover:underline"
                  >
                    Materials
                  </Link>
                  .
                </p>
              )}

              <fieldset className="space-y-2.5">
                <legend className="text-sm font-medium">Options</legend>
                <div className="flex items-center gap-2.5">
                  <Checkbox
                    id="quiz"
                    checked={withQuiz}
                    onCheckedChange={(v) => setWithQuiz(v === true)}
                  />
                  <Label htmlFor="quiz" className="text-sm font-normal">
                    Add practice questions to each section
                  </Label>
                </div>
                {hasStyle ? (
                  <div className="flex items-center gap-2.5">
                    <Checkbox
                      id="style"
                      checked={useStyle}
                      onCheckedChange={(v) => setUseStyle(v === true)}
                    />
                    <Label htmlFor="style" className="text-sm font-normal">
                      Write in my style
                    </Label>
                  </div>
                ) : null}
              </fieldset>

              <Button
                onClick={() => void start()}
                disabled={!goal.trim()}
                className="w-full sm:w-auto"
              >
                Build my course
              </Button>
              <p className="text-sm text-muted-foreground">
                Sections appear as they&apos;re written. You can leave — writing
                continues in the background and everything is saved.
              </p>
            </div>
          </section>

          {error ? (
            <div className="mt-6">
              <RunError message={error} onRetry={() => setError(null)} />
            </div>
          ) : null}

          </div>

          {!loadingLibrary ? (
            <div className="mt-12 lg:mt-0">
              <LibraryList
                courses={library}
                activeId={activeCourseId}
                onOpen={openCourse}
                onDelete={removeCourse}
              />
            </div>
          ) : null}
        </div>
      ) : (
        <CourseReader
          goal={goal}
          summary={summary}
          modules={modules}
          cost={cost}
          generatedHere={generatedHere}
          phase={phase}
          detail={detail}
          error={error}
          running={running}
          modulesDone={modulesDone}
          courseStatus={courseStatus}
          modulesRead={modulesRead}
          activeSection={activeSection}
          courseId={activeCourseId}
          userId={userId}
          titleRef={titleRef}
          onBack={resetView}
          onCancel={() => void stopGeneration()}
          onResume={() => void resumeGeneration()}
          onRetry={() => void start()}
          onMarkRead={(index) => void markRead(index)}
          onSelectSection={setActiveSection}
          onBookmark={(index) => {
            if (activeCourseId != null) {
              void persistProgress(activeCourseId, modulesRead, index);
            }
          }}
        />
      )}
    </div>
  );
}

function CourseReader({
  goal,
  summary,
  modules,
  cost,
  generatedHere,
  phase,
  detail,
  error,
  running,
  modulesDone,
  courseStatus,
  modulesRead,
  activeSection,
  courseId,
  userId,
  titleRef,
  onBack,
  onCancel,
  onResume,
  onRetry,
  onMarkRead,
  onSelectSection,
  onBookmark,
}: {
  goal: string;
  summary: string | null;
  modules: ModuleState[];
  cost: number | null;
  generatedHere: boolean;
  phase: RunPhase;
  detail: string;
  error: string | null;
  running: boolean;
  modulesDone: number;
  courseStatus: "generating" | "complete" | "partial" | null;
  modulesRead: number[];
  activeSection: number;
  courseId: number | null;
  userId: string;
  titleRef: React.RefObject<HTMLHeadingElement | null>;
  onBack: () => void;
  onCancel: () => void;
  onResume: () => void;
  onRetry: () => void;
  onMarkRead: (index: number) => void;
  onSelectSection: (index: number) => void;
  onBookmark: (index: number) => void;
}) {
  const showRunStatus =
    running ||
    courseStatus === "generating" ||
    (generatedHere && phase === "done" && courseStatus === "complete");
  const showResume =
    courseStatus === "partial" && !running && phase !== "writing";

  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Button variant="ghost" size="sm" onClick={onBack}>
          ← Library
        </Button>
        <div className="flex flex-wrap items-center gap-2">
          {showResume ? (
            <Button size="sm" variant="secondary" onClick={onResume}>
              Resume generation
            </Button>
          ) : null}
          {cost != null && generatedHere ? (
            <span className="text-sm text-muted-foreground">
              Cost to build: ${cost.toFixed(2)}
            </span>
          ) : null}
        </div>
      </div>

      <h1
        ref={titleRef}
        tabIndex={-1}
        className="mt-4 font-heading text-2xl tracking-tight text-ink outline-none sm:text-3xl"
      >
        {goal}
      </h1>
      {summary ? (
        <p className="mt-2 max-w-prose text-muted-foreground">{summary}</p>
      ) : null}

      <div className="mt-6 lg:grid lg:grid-cols-[13rem_minmax(0,1fr)] lg:gap-10">
        <SectionRail
          modules={modules}
          activeIndex={activeSection}
          readIndices={modulesRead}
          onSelect={(index) => {
            onSelectSection(index);
            onBookmark(index);
          }}
        />

        <div className="min-w-0">
          <div className="space-y-10">
        {modules.map((m) => (
          <div
            key={m.index}
            id={`section-${m.index}`}
            className="animate-in fade-in duration-300"
          >
            <ModulePanel
              module={m}
              read={modulesRead.includes(m.index)}
              courseId={courseId}
              userId={userId}
              onMarkRead={() => onMarkRead(m.index)}
              onVisible={() => {
                onSelectSection(m.index);
              }}
            />
          </div>
        ))}
          </div>
        </div>
      </div>
    </>
  );
}
