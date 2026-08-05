"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
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
import {
  loadCachedCourse,
  saveCachedCourse,
  type CachedCourse,
} from "@/lib/course-cache";
import type {
  ModuleState,
  NamespaceInfo,
  SavedCourseSummary,
} from "@/lib/types";
import { getStoredUser, setStoredUser } from "@/lib/user";
import { cn } from "@/lib/utils";

import { HistoryPanel } from "./history-panel";
import { ModulePanel } from "./module-panel";

type Phase =
  | "idle"
  | "planning"
  | "ingesting"
  | "generating"
  | "done"
  | "error";

const AUTO_NS = "__auto__";

export function CourseWorkspace() {
  const [goal, setGoal] = useState("");
  const [user, setUser] = useState("");
  const [namespace, setNamespace] = useState(AUTO_NS);
  const [namespaces, setNamespaces] = useState<NamespaceInfo[]>([]);
  const [history, setHistory] = useState<SavedCourseSummary[]>([]);
  const [activeCourseId, setActiveCourseId] = useState<number | null>(null);
  const [withQuiz, setWithQuiz] = useState(true);
  const [useStyle, setUseStyle] = useState(false);
  const [skipIngest, setSkipIngest] = useState(false);
  const [phase, setPhase] = useState<Phase>("idle");
  const [statusLine, setStatusLine] = useState("");
  const [summary, setSummary] = useState<string | null>(null);
  const [activeNamespace, setActiveNamespace] = useState<string | null>(null);
  const [modules, setModules] = useState<ModuleState[]>([]);
  const [cost, setCost] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const resultsRef = useRef<HTMLDivElement | null>(null);

  const historyUser = user.trim() || "anonymous";

  const refreshHistory = useCallback(async (who?: string) => {
    try {
      const rows = await listCourses(who ?? historyUser);
      setHistory(rows);
    } catch {
      setHistory([]);
    }
  }, [historyUser]);

  function applyCached(cached: CachedCourse) {
    setActiveCourseId(cached.id);
    setGoal(cached.goal);
    setSummary(cached.summary);
    setActiveNamespace(cached.namespace);
    setCost(cached.cost);
    setModules(cached.modules);
    setError(null);
    setStatusLine("");
    setPhase("done");
  }

  useEffect(() => {
    let cancelled = false;
    Promise.resolve().then(() => {
      if (cancelled) return;
      const stored = getStoredUser();
      setUser(stored);
      const cached = loadCachedCourse();
      if (cached?.modules?.length) {
        applyCached(cached);
      }
      getNamespaces()
        .then((rows) => {
          if (!cancelled) setNamespaces(rows);
        })
        .catch(() => {
          if (!cancelled) setNamespaces([]);
        });
      listCourses(stored.trim() || "anonymous")
        .then((rows) => {
          if (!cancelled) setHistory(rows);
        })
        .catch(() => {
          if (!cancelled) setHistory([]);
        });
    });
    return () => {
      cancelled = true;
    };
  }, []);

  function persistLocal(partial: {
    id?: number | null;
    goal?: string;
    summary?: string | null;
    namespace?: string | null;
    cost?: number | null;
    modules?: ModuleState[];
    user?: string;
  }) {
    const snapshot: CachedCourse = {
      id: partial.id ?? activeCourseId,
      user: partial.user ?? (user.trim() || "anonymous"),
      goal: partial.goal ?? goal,
      summary: partial.summary ?? summary,
      namespace: partial.namespace ?? activeNamespace,
      cost: partial.cost !== undefined ? partial.cost : cost,
      modules: partial.modules ?? modules,
      savedAt: new Date().toISOString(),
    };
    if (snapshot.modules.length) saveCachedCourse(snapshot);
  }

  // Keep the last finished course in the browser so refresh/reopen shows it
  // even before/without clicking History.
  useEffect(() => {
    if (phase !== "done" || modules.length === 0) return;
    saveCachedCourse({
      id: activeCourseId,
      user: user.trim() || "anonymous",
      goal,
      summary,
      namespace: activeNamespace,
      cost,
      modules,
      savedAt: new Date().toISOString(),
    });
  }, [
    phase,
    modules,
    activeCourseId,
    user,
    goal,
    summary,
    activeNamespace,
    cost,
  ]);

  const running =
    phase === "planning" || phase === "ingesting" || phase === "generating";

  const progressLabel = useMemo(() => {
    if (phase === "planning") return "Planning syllabus";
    if (phase === "ingesting") return statusLine || "Ingesting corpus";
    if (phase === "generating") {
      const done = modules.filter((m) =>
        ["done", "refused", "error"].includes(m.status),
      ).length;
      return `Writing modules ${done}/${modules.length || "…"}`;
    }
    if (phase === "done" && activeCourseId != null) {
      return `Saved course #${activeCourseId}`;
    }
    if (phase === "done") return "Course ready";
    return null;
  }, [phase, statusLine, modules, activeCourseId]);

  function clearView() {
    abortRef.current?.abort();
    setActiveCourseId(null);
    setPhase("idle");
    setStatusLine("");
    setSummary(null);
    setActiveNamespace(null);
    setModules([]);
    setCost(null);
    setError(null);
  }

  async function openSaved(id: number) {
    if (running) return;
    try {
      const course = await getCourse(id);
      const nextModules: ModuleState[] = course.modules.map((m) => ({
        index: m.index,
        title: m.title,
        streamingText: m.notes?.body ?? "",
        notes: m.notes,
        error: m.error,
        status: m.error
          ? "error"
          : m.notes?.refused
            ? "refused"
            : "done",
      }));
      const nextCost =
        course.estimated_cost_usd != null
          ? Number(course.estimated_cost_usd)
          : null;
      setActiveCourseId(course.id);
      setGoal(course.goal);
      setSummary(course.summary);
      setActiveNamespace(course.namespace);
      setCost(nextCost);
      setError(null);
      setStatusLine("");
      setModules(nextModules);
      setPhase("done");
      persistLocal({
        id: course.id,
        goal: course.goal,
        summary: course.summary,
        namespace: course.namespace,
        cost: nextCost,
        modules: nextModules,
      });
      requestAnimationFrame(() => {
        resultsRef.current?.scrollIntoView({
          behavior: "smooth",
          block: "start",
        });
      });
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  async function onDelete(id: number) {
    try {
      await deleteCourse(id, historyUser);
      if (activeCourseId === id) clearView();
      await refreshHistory();
      toast.success("Removed from history");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = goal.trim();
    if (!trimmed || running) return;

    if (!user.trim()) {
      toast.message("Saving as anonymous — set a user id to keep history yours");
    }

    setStoredUser(user);
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setActiveCourseId(null);
    setPhase("planning");
    setStatusLine("");
    setSummary(null);
    setActiveNamespace(null);
    setModules([]);
    setCost(null);
    setError(null);

    requestAnimationFrame(() => {
      resultsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    });

    try {
      for await (const event of streamCourse(
        {
          goal: trimmed,
          namespace: namespace === AUTO_NS ? null : namespace,
          user: user.trim() || "anonymous",
          use_style: useStyle && Boolean(user.trim()),
          with_quiz: withQuiz,
          skip_ingest: skipIngest || namespace !== AUTO_NS,
          limit: 10,
        },
        controller.signal,
      )) {
        switch (event.type) {
          case "planning":
            setPhase("planning");
            break;
          case "syllabus":
            setSummary(event.summary);
            setActiveNamespace(event.namespace);
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
            setPhase("generating");
            break;
          case "ingesting":
            setPhase("ingesting");
            setStatusLine(`Indexing ${event.namespace}…`);
            setActiveNamespace(event.namespace);
            break;
          case "ingested":
            setStatusLine(
              event.cached
                ? `Corpus cached · ${event.chunks} chunks`
                : `Indexed ${event.chunks} chunks`,
            );
            break;
          case "module_start":
            setModules((prev) =>
              prev.map((m) =>
                m.index === event.index
                  ? { ...m, title: event.title, status: "streaming" }
                  : m,
              ),
            );
            setPhase("generating");
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
                      streamingText: event.notes.body || m.streamingText,
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
            getNamespaces().then(setNamespaces).catch(() => undefined);
            break;
          case "saved":
            setActiveCourseId(event.id);
            setPhase("done");
            toast.success(`Saved to history (#${event.id})`);
            void refreshHistory(user.trim() || "anonymous");
            break;
          case "error":
            setError(event.error);
            setPhase("error");
            toast.error(event.error);
            break;
        }
      }
      setPhase((p) => (p === "error" ? p : "done"));
    } catch (err) {
      if ((err as Error).name === "AbortError") return;
      const message = err instanceof Error ? err.message : String(err);
      setError(message);
      setPhase("error");
      toast.error(message);
    }
  }

  function stop() {
    abortRef.current?.abort();
    setPhase((p) => (p === "done" || p === "idle" ? p : "done"));
  }

  return (
    <div className="mx-auto w-full max-w-6xl px-4 pb-20 sm:px-6">
      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_17rem] lg:items-start">
        <div>
          <section
            className={cn(
              "relative overflow-hidden pt-14 pb-10 sm:pt-20 sm:pb-14",
              modules.length === 0 && "min-h-[50vh]",
            )}
          >
            <div
              aria-hidden
              className="pointer-events-none absolute inset-x-0 -top-24 h-[28rem] bg-[radial-gradient(ellipse_at_30%_0%,oklch(0.82_0.06_195_/_0.55),transparent_55%),radial-gradient(ellipse_at_85%_20%,oklch(0.88_0.05_75_/_0.45),transparent_45%)]"
            />
            <div className="relative">
              <p className="font-mono text-[0.7rem] tracking-[0.18em] text-primary/80 uppercase">
                Grounded study notes
              </p>
              <h1 className="font-heading mt-3 max-w-xl text-5xl leading-[1.05] tracking-tight text-ink sm:text-6xl">
                NoteKit
              </h1>
              <p className="mt-4 max-w-md text-base leading-relaxed text-muted-foreground sm:text-lg">
                Turn a learning goal into cited course notes from real sources —
                streamed once, then saved in your history.
              </p>

              <form onSubmit={onSubmit} className="mt-10 max-w-2xl space-y-5">
                <div className="space-y-2">
                  <Label htmlFor="goal">Learning goal</Label>
                  <Textarea
                    id="goal"
                    value={goal}
                    onChange={(e) => setGoal(e.target.value)}
                    placeholder="Teach me Q-learning at an intermediate level"
                    rows={3}
                    className="resize-none bg-background/80 text-base shadow-sm"
                    disabled={running}
                  />
                </div>

                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="space-y-2">
                    <Label htmlFor="namespace">Corpus</Label>
                    <Select
                      value={namespace}
                      onValueChange={(v) => {
                        if (v) {
                          setNamespace(v);
                          if (v !== AUTO_NS) setSkipIngest(true);
                        }
                      }}
                      disabled={running}
                    >
                      <SelectTrigger
                        id="namespace"
                        className="w-full bg-background/80"
                      >
                        <SelectValue placeholder="Auto from goal" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value={AUTO_NS}>
                          Auto — ingest from goal
                        </SelectItem>
                        {namespaces.map((ns) => (
                          <SelectItem key={ns.namespace} value={ns.namespace}>
                            {ns.namespace} · {ns.documents} docs
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="user">User id</Label>
                    <Input
                      id="user"
                      value={user}
                      onChange={(e) => setUser(e.target.value)}
                      onBlur={() => {
                        setStoredUser(user);
                        void refreshHistory(user.trim() || "anonymous");
                      }}
                      placeholder="sriya"
                      className="bg-background/80"
                      disabled={running}
                    />
                  </div>
                </div>

                <div className="flex flex-wrap gap-x-6 gap-y-3 text-sm">
                  <label className="flex items-center gap-2">
                    <Checkbox
                      checked={withQuiz}
                      onCheckedChange={(v) => setWithQuiz(v === true)}
                      disabled={running}
                    />
                    Include quiz
                  </label>
                  <label className="flex items-center gap-2">
                    <Checkbox
                      checked={useStyle}
                      onCheckedChange={(v) => setUseStyle(v === true)}
                      disabled={running || !user.trim()}
                    />
                    Match my style
                  </label>
                  {namespace === AUTO_NS ? (
                    <label className="flex items-center gap-2">
                      <Checkbox
                        checked={skipIngest}
                        onCheckedChange={(v) => setSkipIngest(v === true)}
                        disabled={running}
                      />
                      Skip ingest
                    </label>
                  ) : null}
                </div>

                <div className="flex flex-wrap items-center gap-3 pt-1">
                  <Button
                    type="submit"
                    size="lg"
                    disabled={!goal.trim() || running}
                    className="min-w-36"
                  >
                    {running ? "Generating…" : "Generate course"}
                  </Button>
                  {running ? (
                    <Button type="button" variant="ghost" onClick={stop}>
                      Stop
                    </Button>
                  ) : null}
                  {phase !== "idle" && !running ? (
                    <Button type="button" variant="ghost" onClick={clearView}>
                      New course
                    </Button>
                  ) : null}
                  {useStyle ? (
                    <p className="text-xs text-muted-foreground">
                      Style matching costs ~10 pts faithfulness
                    </p>
                  ) : null}
                </div>
              </form>
            </div>
          </section>

          <div ref={resultsRef} className="space-y-6">
            {phase !== "idle" ? (
              <div className="flex flex-wrap items-end justify-between gap-3 border-b border-border/60 pb-4">
                <div>
                  <p className="font-mono text-[0.65rem] tracking-[0.16em] text-muted-foreground uppercase">
                    {progressLabel}
                  </p>
                  {summary ? (
                    <p className="mt-1 max-w-2xl text-sm text-foreground/90">
                      {summary}
                    </p>
                  ) : null}
                  {activeNamespace ? (
                    <p className="mt-1 font-mono text-xs text-muted-foreground">
                      namespace · {activeNamespace}
                      {cost != null ? ` · ~$${cost.toFixed(2)}` : ""}
                    </p>
                  ) : null}
                </div>
                {running ? (
                  <div className="h-1 w-28 overflow-hidden rounded-full bg-muted">
                    <div className="h-full w-1/2 animate-pulse rounded-full bg-primary" />
                  </div>
                ) : null}
              </div>
            ) : null}

            {error ? (
              <p className="rounded-xl border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
                {error}
              </p>
            ) : null}

            <div className="space-y-6">
              {modules.map((module) => (
                <ModulePanel key={module.index} module={module} />
              ))}
            </div>
          </div>
        </div>

        <div className="pt-14 lg:sticky lg:top-16 lg:pt-20">
          <HistoryPanel
            items={history}
            activeId={activeCourseId}
            user={historyUser}
            onSelect={(id) => void openSaved(id)}
            onDelete={(id) => void onDelete(id)}
            onRefresh={() => void refreshHistory()}
          />
        </div>
      </div>
    </div>
  );
}
