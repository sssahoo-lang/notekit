"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { ContinueCard } from "@/components/continue-card";
import { CourseMap } from "@/components/course-map";
import { scrollToSection } from "@/lib/go-to-section";
import { CourseForm } from "@/components/course-form";
import { LibraryList } from "@/components/library-list";
import { ModulePanel } from "@/components/module-panel";
import { RunError, RunStatus, type RunPhase } from "@/components/run-status";
import { SectionRail } from "@/components/section-rail";
import { Button } from "@/components/ui/button";
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
  // The planner writes a clean `title` precisely so a reader never sees
  // their own typos back. `goal` is the course-form input and cannot serve
  // both jobs.
  const [courseTitle, setCourseTitle] = useState("");
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
  const [error, setError] = useState<string | null>(null);
  const [loadingLibrary, setLoadingLibrary] = useState(true);
  const [generatedHere, setGeneratedHere] = useState(false);
  const [courseStatus, setCourseStatus] = useState<
    "generating" | "complete" | "partial" | null
  >(null);
  const [modulesRead, setModulesRead] = useState<number[]>([]);
  const [showMap, setShowMap] = useState(false);
  const [restore, setRestore] = useState<{
    section: number;
    paragraph: number;
  } | null>(null);
  // Where reading currently is, saved with the bookmark rather than on every
  // scroll — a PATCH per paragraph would be a request every few seconds.
  const paragraphRef = useRef(0);
  const paragraphSaveRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [activeSection, setActiveSection] = useState(0);
  const abortRef = useRef<AbortController | null>(null);
  const titleRef = useRef<HTMLHeadingElement>(null);
  const nav = useCourseNav();

  const userId = profile?.id ?? "anonymous";
  const uploads = useMemo(
    () => (profile ? myUploads(sources, profile.id) : []),
    [sources, profile],
  );

  // Derived rather than corrected in an effect: if the material backing the
  // current choice disappears, fall back to finding sources. Writing this as
  // state-fixing-state caused a cascading render.
  const effectiveSource =
    sourceMode !== AUTO_SOURCE &&
    !uploads.some((ns) => ns.namespace === sourceMode)
      ? AUTO_SOURCE
      : sourceMode;

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
    bookmarkParagraph = 0,
  ) {
    try {
      await saveProgress(courseId, {
        modules_read: read,
        bookmark: { module_index: bookmarkIndex, paragraph: bookmarkParagraph },
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
      const bookmarkPara = course.progress?.bookmark?.paragraph ?? null;

      setActiveCourseId(course.id);
      setGoal(course.goal);
      setCourseTitle(course.title || course.goal);
      setSummary(course.summary);
      setModules(mapped);
      setModulesRead(Array.isArray(read) ? read : []);
      setActiveSection(
        typeof bookmark === "number" && bookmark < mapped.length ? bookmark : 0,
      );
      setRestore(
        typeof bookmark === "number" && typeof bookmarkPara === "number"
          ? { section: bookmark, paragraph: bookmarkPara }
          : null,
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
    if (effectiveSource !== AUTO_SOURCE && !uploadNs) {
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
            namespace: effectiveSource === AUTO_SOURCE ? null : uploadNs,
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
    toast.message("Generation stopped. What’s ready is saved");
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
        <div
          key="home"
          className="rise-in lg:grid lg:grid-cols-[minmax(0,1fr)_22rem] lg:gap-12"
        >
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

          <div className="mt-10">
            <CourseForm
              goal={goal}
              onGoalChange={setGoal}
              sourceMode={effectiveSource}
              onSourceChange={pickSourceMode}
              autoSourceValue={AUTO_SOURCE}
              uploads={uploads}
              userId={userId}
              withQuiz={withQuiz}
              onQuizChange={setWithQuiz}
              useStyle={useStyle}
              onStyleChange={setUseStyle}
              hasStyle={hasStyle}
              onSubmit={() => void start()}
            />
          </div>

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
          courseTitle={courseTitle}
          showMap={showMap}
          onToggleMap={() => setShowMap((prev) => !prev)}
          titleRef={titleRef}
          onBack={resetView}
          onCancel={() => void stopGeneration()}
          onResume={() => void resumeGeneration()}
          onRetry={() => void start()}
          onMarkRead={(index) => void markRead(index)}
          onSelectSection={setActiveSection}
          onBookmark={(index, paragraph) => {
            if (activeCourseId != null) {
              void persistProgress(
                activeCourseId,
                modulesRead,
                index,
                paragraph ?? paragraphRef.current,
              );
            }
          }}
          onParagraph={(paragraph) => {
            if (paragraphRef.current === paragraph) return;
            paragraphRef.current = paragraph;
            // Debounced: a PATCH per paragraph would fire every few seconds
            // while reading. Two seconds after scrolling settles is enough to
            // survive closing the tab.
            if (paragraphSaveRef.current) clearTimeout(paragraphSaveRef.current);
            paragraphSaveRef.current = setTimeout(() => {
              if (activeCourseId != null) {
                void persistProgress(
                  activeCourseId,
                  modulesRead,
                  activeSection,
                  paragraph,
                );
              }
            }, 2000);
          }}
          restore={restore}
        />
      )}
    </div>
  );
}

function CourseReader({
  goal,
  summary,
  modules,
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
  courseTitle,
  showMap,
  onToggleMap,
  titleRef,
  onBack,
  onCancel,
  onResume,
  onRetry,
  onMarkRead,
  onSelectSection,
  onBookmark,
  onParagraph,
  restore,
}: {
  goal: string;
  summary: string | null;
  modules: ModuleState[];
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
  courseTitle: string;
  showMap: boolean;
  onToggleMap: () => void;
  titleRef: React.RefObject<HTMLHeadingElement | null>;
  onBack: () => void;
  onCancel: () => void;
  onResume: () => void;
  onRetry: () => void;
  onMarkRead: (index: number) => void;
  onSelectSection: (index: number) => void;
  onBookmark: (index: number, paragraph?: number) => void;
  onParagraph: (paragraph: number) => void;
  restore: { section: number; paragraph: number } | null;
}) {
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [showCitations, setShowCitations] = useState(true);

  useEffect(() => {
    // Reads localStorage, which is unavailable during SSR; running this in a
    // lazy initializer instead would make the server's default and the
    // client's stored preference disagree on first paint.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setShowCitations(localStorage.getItem("notekit.citations") !== "off");
  }, []);

  function toggleCitations() {
    setShowCitations((prev) => {
      localStorage.setItem("notekit.citations", prev ? "off" : "on");
      return !prev;
    });
  }

  // Open where the reader left off, and nothing else. Re-runs when the course
  // changes so opening a different one does not inherit the last one's state.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setExpanded(new Set([activeSection]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [courseId]);

  // A section being written must be visible, or streaming happens off-screen.
  useEffect(() => {
    const live = modules
      .filter((m) => m.status === "streaming" || m.status === "pending")
      .map((m) => m.index);
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (live.length) setExpanded((prev) => new Set([...prev, ...live]));
  }, [modules]);

  const allOpen = expanded.size >= modules.length && modules.length > 0;

  function toggleSection(index: number) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  }

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
        </div>
      </div>

      <h1
        ref={titleRef}
        tabIndex={-1}
        className="mt-4 font-heading text-2xl tracking-tight text-ink outline-none sm:text-3xl"
      >
        {courseTitle || goal}
      </h1>
      {summary ? (
        <p className="mt-2 max-w-prose text-muted-foreground">{summary}</p>
      ) : null}

      {showRunStatus ? (
        <div className="mt-6">
          <RunStatus
            phase={phase}
            detail={detail}
            modulesDone={modulesDone}
            modulesTotal={modules.length}
            onCancel={running ? onCancel : undefined}
          />
        </div>
      ) : null}

      {/* A failure part-way through a course was previously silent here. */}
      {error ? (
        <div className="mt-4">
          <RunError message={error} onRetry={onRetry} />
        </div>
      ) : null}

      <div className="mt-6 lg:grid lg:grid-cols-[13rem_minmax(0,1fr)] lg:gap-10">
        <SectionRail
          modules={modules}
          activeIndex={activeSection}
          readIndices={modulesRead}
          onSelect={(index) => {
            onSelectSection(index);
            onBookmark(index, 0);
            // Jumping to a collapsed section should reveal it.
            setExpanded((prev) => new Set([...prev, index]));
          }}
        />

        <div className="min-w-0">
          {modules.length > 1 ? (
            <div className="mb-4 flex flex-wrap justify-end gap-1">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="text-muted-foreground hover:text-foreground"
                onClick={onToggleMap}
                aria-pressed={showMap}
              >
                {showMap ? "Hide map" : "Course map"}
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="text-muted-foreground hover:text-foreground"
                onClick={toggleCitations}
                aria-pressed={!showCitations}
              >
                {showCitations ? "Hide citations" : "Show citations"}
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="text-muted-foreground hover:text-foreground"
                onClick={() =>
                  setExpanded(
                    allOpen
                      ? new Set()
                      : new Set(modules.map((m) => m.index)),
                  )
                }
              >
                {allOpen ? "Collapse all" : "Expand all"}
              </Button>
            </div>
          ) : null}

          {showMap ? (
            <div className="rise-in mb-8">
              <CourseMap
                modules={modules}
                activeSection={activeSection}
                onSelectSection={(index) => {
                  onSelectSection(index);
                  onBookmark(index, 0);
                  setExpanded((prev) => new Set([...prev, index]));
                  scrollToSection(index);
                }}
              />
            </div>
          ) : null}

          <div className="space-y-6">
        {modules.map((m) => (
          <div
            key={m.index}
            id={`section-${m.index}`}
            className="rise-in"
          >
            <ModulePanel
              module={m}
              read={modulesRead.includes(m.index)}
              courseId={courseId}
              userId={userId}
              expanded={expanded.has(m.index)}
              onToggle={() => toggleSection(m.index)}
              showCitations={showCitations}
              onParagraph={
                m.index === activeSection ? onParagraph : undefined
              }
              restoreParagraph={
                restore && restore.section === m.index ? restore.paragraph : null
              }
              onAdvance={
                m.index + 1 < modules.length
                  ? () => {
                      const next = m.index + 1;
                      setExpanded((prev) => new Set([...prev, next]));
                      onSelectSection(next);
                      onBookmark(next, 0);
                      requestAnimationFrame(() => {
                        const el = document.getElementById(`section-${next}`);
                        const reduced = window.matchMedia(
                          "(prefers-reduced-motion: reduce)",
                        ).matches;
                        el?.scrollIntoView({
                          behavior: reduced ? "auto" : "smooth",
                          block: "start",
                        });
                      });
                    }
                  : undefined
              }
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
