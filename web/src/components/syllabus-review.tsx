"use client";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { Syllabus, SyllabusModule } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * The outline, before any of it is written.
 *
 * Planning costs a fraction of a cent and generation costs roughly a hundred
 * times that, yet the first time a reader saw the syllabus was after the
 * expensive part. Most "this is not what I asked for" outcomes are decided
 * here, in which sections exist and what each one promises, so this is where
 * the reader gets to say so.
 *
 * Titles and goals are editable; the retrieval query behind each section is
 * not shown, because it is written for a search engine rather than a person.
 * A section the reader adds gets its title as its query, which the planner
 * would have done worse at guessing anyway.
 */

type Props = {
  syllabus: Syllabus;
  onChange: (next: Syllabus) => void;
  onConfirm: () => void;
  onBack: () => void;
};

const MAX_SECTIONS = 8;

export function SyllabusReview({ syllabus, onChange, onConfirm, onBack }: Props) {
  const modules = syllabus.modules;

  const setModule = (index: number, patch: Partial<SyllabusModule>) =>
    onChange({
      ...syllabus,
      modules: modules.map((m, i) => (i === index ? { ...m, ...patch } : m)),
    });

  const move = (index: number, delta: number) => {
    const target = index + delta;
    if (target < 0 || target >= modules.length) return;
    const next = [...modules];
    [next[index], next[target]] = [next[target], next[index]];
    onChange({ ...syllabus, modules: next });
  };

  const remove = (index: number) =>
    onChange({ ...syllabus, modules: modules.filter((_, i) => i !== index) });

  const add = () =>
    onChange({
      ...syllabus,
      modules: [...modules, { title: "", query: "", learning_goals: [""] }],
    });

  const valid =
    modules.length > 0 &&
    modules.length <= MAX_SECTIONS &&
    modules.every((m) => m.title.trim() && m.learning_goals.some((g) => g.trim()));

  return (
    <section aria-labelledby="review-heading">
      <h2 id="review-heading" className="text-lg font-medium text-ink">
        Check the outline before it is written
      </h2>
      <p className="mt-1 text-sm text-muted-foreground">
        Rename, reorder or remove sections, and edit what each should teach.
        Nothing costs anything until you confirm.
      </p>

      <div className="mt-4 rounded-2xl border border-border/80 bg-card/90 p-5 sm:p-6">
        <Label htmlFor="review-title" className="text-sm font-normal">
          Course title
        </Label>
        <Input
          id="review-title"
          value={syllabus.title}
          onChange={(e) => onChange({ ...syllabus, title: e.target.value })}
          className="mt-1.5"
        />
        <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
          {syllabus.summary}
        </p>

        <ol className="mt-6 space-y-4">
          {modules.map((m, i) => (
            <li
              key={i}
              className="rounded-xl border border-border/70 bg-background/60 p-4"
            >
              <div className="flex items-start gap-3">
                <span className="mt-2 font-mono text-xs text-muted-foreground">
                  {String(i + 1).padStart(2, "0")}
                </span>
                <div className="min-w-0 flex-1 space-y-3">
                  <div>
                    <Label htmlFor={`section-${i}-title`} className="sr-only">
                      Section {i + 1} title
                    </Label>
                    <Input
                      id={`section-${i}-title`}
                      value={m.title}
                      placeholder="Section title"
                      onChange={(e) =>
                        setModule(i, {
                          title: e.target.value,
                          query: m.query || e.target.value,
                        })
                      }
                      className="font-medium"
                    />
                  </div>
                  <div>
                    <Label
                      htmlFor={`section-${i}-goals`}
                      className="text-xs text-muted-foreground"
                    >
                      What the reader should be able to do afterwards, one per line
                    </Label>
                    <Textarea
                      id={`section-${i}-goals`}
                      value={m.learning_goals.join("\n")}
                      rows={Math.max(2, m.learning_goals.length)}
                      onChange={(e) =>
                        setModule(i, { learning_goals: e.target.value.split("\n") })
                      }
                      className="mt-1 resize-y text-sm"
                    />
                  </div>
                </div>
                <div className="flex shrink-0 flex-col gap-1">
                  {[
                    { label: "Move up", delta: -1, disabled: i === 0 },
                    { label: "Move down", delta: 1, disabled: i === modules.length - 1 },
                  ].map((b) => (
                    <button
                      key={b.label}
                      type="button"
                      aria-label={`${b.label}: section ${i + 1}`}
                      disabled={b.disabled}
                      onClick={() => move(i, b.delta)}
                      className={cn(
                        "rounded-md px-2 py-1 text-xs text-foreground/70 hover:bg-muted",
                        "disabled:opacity-30 focus-visible:outline-2 focus-visible:outline-ring",
                      )}
                    >
                      {b.delta < 0 ? "↑" : "↓"}
                    </button>
                  ))}
                  <button
                    type="button"
                    aria-label={`Remove section ${i + 1}`}
                    onClick={() => remove(i)}
                    className="rounded-md px-2 py-1 text-xs text-destructive/80 hover:bg-destructive/10 focus-visible:outline-2 focus-visible:outline-ring"
                  >
                    ×
                  </button>
                </div>
              </div>
            </li>
          ))}
        </ol>

        <div className="mt-4">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={add}
            disabled={modules.length >= MAX_SECTIONS}
          >
            Add a section
          </Button>
          {modules.length >= MAX_SECTIONS ? (
            <span className="ml-3 text-xs text-muted-foreground">
              Eight is the most a course can hold.
            </span>
          ) : null}
        </div>

        <div className="mt-6 flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-border/70 pt-5">
          <Button onClick={onConfirm} disabled={!valid} size="lg" className="w-full sm:w-auto">
            Write the course
          </Button>
          <Button type="button" variant="ghost" onClick={onBack}>
            Back
          </Button>
          {!valid ? (
            <p className="text-sm text-muted-foreground">
              Every section needs a title and at least one goal.
            </p>
          ) : null}
        </div>
      </div>
    </section>
  );
}
