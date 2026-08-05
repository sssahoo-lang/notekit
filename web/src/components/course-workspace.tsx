"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { ContinueCard, isFinished } from "@/components/continue-card";
import { LibraryList } from "@/components/library-list";
import { RunError, RunStatus, type RunPhase } from "@/components/run-status";
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
  deleteCourse,
  getCourse,
  getNamespaces,
  listCourses,
  streamCourse,
} from "@/lib/api";
import { clearCachedCourse } from "@/lib/course-cache";
import { getProfile, greetingName, type Profile } from "@/lib/profile";
import type {
  ModuleState,
  NamespaceInfo,
  SavedCourseSummary,
} from "@/lib/types";

import { ModulePanel } from "./module-panel";

const AUTO_SOURCE = "__auto__";

/** Turn a storage namespace into something a reader recognises. */
function sourceLabel(ns: NamespaceInfo): string {
  if (ns.namespace.startsWith("user-")) {
    const topic = ns.namespace.split("-").slice(2).join(" ") || "notes";
    return `Your uploaded material — ${topic}`;
  }
  return ns.namespace.replace(/-/g, " ");
}

export function CourseWorkspace() {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [goal, setGoal] = useState("");
  const [source, setSource] = useState(AUTO_SOURCE);
  const [sources, setSources] = useState<NamespaceInfo[]>([]);
  const [library, setLibrary] = useState<SavedCourseSummary[]>([]);
  const [activeCourseId, setActiveCourseId] = useState<number | null>(null);
  const [withQuiz, setWithQuiz] = useState(true);
  const [useStyle, setUseStyle] = useState(false);
  const [phase, setPhase] = useState<RunPhase>("idle");
  const [detail, setDetail] = useState("");
  const [summary, setSummary] = useState<string | null>(null);
  const [modules, setModules] = useState<ModuleState[]>([]);
  const [cost, setCost] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loadingLibrary, setLoadingLibrary] = useState(true);
  const [generatedHere, setGeneratedHere] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const userId = profile?.id ?? "anonymous";

  const refreshLibrary = useCallback(async (id: string) => {
    try {
      setLibrary(await listCourses(id));
    } catch {
      setLibrary([]);
    } finally {
      setLoadingLibrary(false);
    }
  }, []);

  useEffect(() => {
    const p = getProfile();
    setProfile(p);
    void refreshLibrary(p.id);
    getNamespaces()
      .then(setSources)
      .catch(() => setSources([]));
  }, [refreshLibrary]);

  const running =
    phase === "planning" || phase === "gathering" || phase === "writing";
  const viewingCourse = modules.length > 0;

  const modulesDone = useMemo(
    () =>
      modules.filter((m) => ["done", "refused", "error"].includes(m.status))
        .length,
    [modules],
  );

  // The newest course still worth returning to.
  const continueCourse = useMemo(
    () => library.find((c) => !isFinished(c)) ?? null,
    [library],
  );

  function resetView() {
    abortRef.current?.abort();
    setActiveCourseId(null);
    setPhase("idle");
    setDetail("");
    setSummary(null);
    setModules([]);
    setCost(null);
    setError(null);
    clearCachedCourse();
  }

  async function openCourse(id: number) {
    setError(null);
    try {
      const course = await getCourse(id);
      setActiveCourseId(course.id);
      setGoal(course.goal);
      setSummary(course.summary);
      setCost(course.estimated_cost_usd);
      setModules(
        course.modules.map((m) => ({
          index: m.index,
          title: m.title,
          streamingText: "",
          notes: m.notes,
          error: m.error,
          status: m.error
            ? "error"
            : m.notes?.refused
              ? "refused"
              : "done",
        })),
      );
      setPhase("done");
      setGeneratedHere(false);
      void refreshLibrary(userId);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function removeCourse(id: number) {
    try {
      await deleteCourse(id, userId);
      if (id === activeCourseId) resetView();
      void refreshLibrary(userId);
      toast.success("Course deleted");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  async function start() {
    if (!goal.trim() || running) return;

    const controller = new AbortController();
    abortRef.current = controller;

    setError(null);
    setActiveCourseId(null);
    setModules([]);
    setSummary(null);
    setCost(null);
    setPhase("planning");
    setDetail("");
    setGeneratedHere(true);

    try {
      for await (const event of streamCourse(
        {
          goal: goal.trim(),
          user: userId,
          use_style: useStyle,
          with_quiz: withQuiz,
          namespace: source === AUTO_SOURCE ? null : source,
        },
        controller.signal,
      )) {
        switch (event.type) {
          case "planning":
            setPhase("planning");
            break;
          case "syllabus":
            setSummary(event.summary);
            setModules(
              event.modules.map((title, index) => ({
                index,
                title,
                streamingText: "",
                notes: null,
                error: null,
                status: "pending",
              })),
            );
            setPhase("writing");
            break;
          case "ingesting":
            setPhase("gathering");
            break;
          case "ingested":
            setDetail(
              event.cached
                ? "Reusing sources gathered earlier."
                : `Read ${event.chunks} passages.`,
            );
            setPhase("writing");
            break;
          case "module_start":
            setPhase("writing");
            break;
          case "token":
            setModules((prev) =>
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
            setModules((prev) =>
              prev.map((m) =>
                m.index === event.index
                  ? {
                      ...m,
                      notes: event.notes,
                      status: event.notes.refused ? "refused" : "done",
                    }
                  : m,
              ),
            );
            break;
          case "module_error":
            setModules((prev) =>
              prev.map((m) =>
                m.index === event.index
                  ? { ...m, error: event.error, status: "error" }
                  : m,
              ),
            );
            break;
          case "done":
            setCost(event.estimated_cost_usd);
            setPhase("done");
            getNamespaces().then(setSources).catch(() => undefined);
            break;
          case "saved":
            setActiveCourseId(event.id);
            setPhase("done");
            void refreshLibrary(userId);
            break;
          case "error":
            setError(event.error);
            setPhase("error");
            break;
        }
      }
      setPhase((p) => (p === "error" ? p : "done"));
    } catch (err) {
      if ((err as Error).name === "AbortError") {
        setPhase("idle");
        return;
      }
      setError(err instanceof Error ? err.message : String(err));
      setPhase("error");
    }
  }

  const showHome = !running && !viewingCourse;

  return (
    <div id="main" className="mx-auto w-full max-w-3xl px-4 py-10 sm:px-6">
      {showHome ? (
        <>
          <h1 className="font-heading text-3xl tracking-tight text-ink">
            {profile?.name
              ? `Welcome back, ${greetingName(profile)}`
              : "What do you want to learn?"}
          </h1>
          <p className="mt-2 max-w-prose text-muted-foreground">
            NoteKit writes study notes from real sources and shows you where
            every claim came from. If the sources don&apos;t cover something, it
            says so instead of guessing.
          </p>

          {continueCourse ? (
            <div className="mt-8">
              <ContinueCard course={continueCourse} onOpen={openCourse} />
            </div>
          ) : null}

          <section aria-labelledby="new-heading" className="mt-10">
            <h2 id="new-heading" className="text-lg font-medium text-ink">
              {continueCourse ? "Or study something new" : "Start studying"}
            </h2>

            <div className="mt-4 space-y-4 rounded-2xl border border-border bg-card p-5">
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
                <p id="goal-help" className="mt-1.5 text-sm text-muted-foreground">
                  Be specific about the level you want — it changes how the
                  notes are written.
                </p>
              </div>

              <div>
                <Label htmlFor="source" className="text-sm font-medium">
                  Where should the notes come from?
                </Label>
                <Select value={source} onValueChange={setSource}>
                  <SelectTrigger id="source" className="mt-2">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={AUTO_SOURCE}>
                      Find sources for me
                    </SelectItem>
                    {sources.map((ns) => (
                      <SelectItem key={ns.namespace} value={ns.namespace}>
                        {sourceLabel(ns)} ({ns.documents} documents)
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

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
                <div className="flex items-center gap-2.5">
                  <Checkbox
                    id="style"
                    checked={useStyle}
                    onCheckedChange={(v) => setUseStyle(v === true)}
                  />
                  <Label htmlFor="style" className="text-sm font-normal">
                    Write in my style
                    <span className="ml-1 text-muted-foreground">
                      (set it up under Writing style)
                    </span>
                  </Label>
                </div>
              </fieldset>

              <Button
                onClick={start}
                disabled={!goal.trim()}
                className="w-full sm:w-auto"
              >
                Build my course
              </Button>
              <p className="text-sm text-muted-foreground">
                Takes about a minute. Sections appear as they&apos;re written,
                and everything is saved automatically.
              </p>
            </div>
          </section>

          {error ? (
            <div className="mt-6">
              <RunError message={error} onRetry={() => setError(null)} />
            </div>
          ) : null}

          {!loadingLibrary ? (
            <div className="mt-12">
              <LibraryList
                courses={library}
                activeId={activeCourseId}
                onOpen={openCourse}
                onDelete={removeCourse}
              />
            </div>
          ) : null}
        </>
      ) : (
        <>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <Button variant="ghost" size="sm" onClick={resetView}>
              ← All courses
            </Button>
            {cost != null ? (
              <span className="text-sm text-muted-foreground">
                Cost to build: ${cost.toFixed(2)}
              </span>
            ) : null}
          </div>

          <h1 className="mt-4 font-heading text-2xl tracking-tight text-ink">
            {goal}
          </h1>
          {summary ? (
            <p className="mt-2 max-w-prose text-muted-foreground">{summary}</p>
          ) : null}

          <div className="mt-6">
            <RunStatus
              phase={phase === "done" && !generatedHere ? "idle" : phase}
              detail={detail}
              modulesDone={modulesDone}
              modulesTotal={modules.length}
              onCancel={running ? () => abortRef.current?.abort() : undefined}
            />
          </div>

          {error ? (
            <div className="mt-4">
              <RunError message={error} onRetry={start} />
            </div>
          ) : null}

          <div className="mt-6 space-y-6">
            {modules.map((m) => (
              <ModulePanel key={m.index} module={m} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
