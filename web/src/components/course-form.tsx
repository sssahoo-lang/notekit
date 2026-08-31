"use client";

import Link from "next/link";

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
import type { NamespaceInfo, NotePreferences } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * Starting a course: the one thing everyone comes here to do.
 *
 * The previous version laid every control out flat, so the thing that decides
 * the whole course looked exactly as important as a checkbox, and four separate
 * lines of grey helper text competed with all of it. Three changes:
 *
 * 1. The goal is the hero. It is large, it is first, and nothing shares its
 *    weight.
 * 2. Examples are offered. An empty box asking "what do you want to learn?" is
 *    a blank-page problem; one click of a realistic prompt shows the shape of a
 *    good answer far better than a sentence explaining it.
 * 3. Everything optional is behind a disclosure, summarised so it need not be
 *    opened to know what it does.
 *
 * Shaping controls live in their own disclosure rather than beside the quiz and
 * source checkboxes, because they answer a different question. "Options" is
 * what to include and where from; "How it is written" is form. Mixing the two
 * made a list of seven unrelated things.
 */

/** A choice the reader has not made is not the same as one they made against,
 * so every control offers Auto rather than defaulting a preference on. Auto
 * sends nothing at all and the notes generate as they always did. */
function Choice<T extends string | boolean>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T | undefined;
  options: { value: T; label: string }[];
  onChange: (value: T | undefined) => void;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1.5">
      <span className="text-sm text-foreground/80">{label}</span>
      <div role="group" aria-label={label} className="flex flex-wrap gap-1">
        {[{ value: undefined, label: "Auto" }, ...options].map((option) => {
          const active = value === option.value;
          return (
            <button
              key={option.label}
              type="button"
              aria-pressed={active}
              onClick={() => onChange(option.value as T | undefined)}
              className={cn(
                "rounded-full border px-2.5 py-1 text-xs transition-colors duration-150",
                "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
                active
                  ? "border-primary/40 bg-primary/10 font-medium text-primary"
                  : "border-border bg-background text-foreground/65 hover:border-primary/30 hover:text-foreground",
              )}
            >
              {option.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

const YES_NO = [
  { value: true as const, label: "Yes" },
  { value: false as const, label: "No" },
];

const EXAMPLES = [
  "Teach me Q-learning at an intermediate level",
  "Explain how transformers work, assume I know linear algebra",
  "Bayesian statistics from scratch",
];

type Props = {
  goal: string;
  onGoalChange: (value: string) => void;
  sourceMode: string;
  onSourceChange: (value: string | null) => void;
  autoSourceValue: string;
  uploads: NamespaceInfo[];
  userId: string;
  withQuiz: boolean;
  onQuizChange: (value: boolean) => void;
  useStyle: boolean;
  onStyleChange: (value: boolean) => void;
  hasStyle: boolean;
  prefs: NotePreferences;
  onPrefsChange: (value: NotePreferences) => void;
  onSubmit: () => void;
};

export function CourseForm({
  goal,
  onGoalChange,
  sourceMode,
  onSourceChange,
  autoSourceValue,
  uploads,
  userId,
  withQuiz,
  onQuizChange,
  useStyle,
  onStyleChange,
  hasStyle,
  prefs,
  onPrefsChange,
  onSubmit,
}: Props) {
  const usingOwnFiles = sourceMode !== autoSourceValue;

  const set = <K extends keyof NotePreferences>(
    key: K,
    value: NotePreferences[K],
  ) => {
    // Auto removes the key rather than storing undefined, so the request body
    // carries only what was actually chosen.
    const next = { ...prefs };
    if (value === undefined) delete next[key];
    else next[key] = value;
    onPrefsChange(next);
  };

  const chosen = Object.keys(prefs).length;

  // Summarised on the closed disclosure, so the defaults are legible without
  // opening it.
  const optionSummary = [
    withQuiz ? "practice questions" : null,
    useStyle ? "your writing style" : null,
    usingOwnFiles ? "your own files" : null,
  ].filter(Boolean);

  return (
    <section aria-labelledby="new-heading">
      <h2 id="new-heading" className="text-lg font-medium text-ink">
        Start a course
      </h2>

      <div className="mt-4 rounded-2xl border border-border/80 bg-card/90 p-5 shadow-[0_1px_0_oklch(0.9_0.01_220)] sm:p-6">
        <Label htmlFor="goal" className="text-base font-medium text-ink">
          What do you want to learn?
        </Label>

        <Textarea
          id="goal"
          value={goal}
          onChange={(e) => onGoalChange(e.target.value)}
          rows={3}
          className="mt-3 resize-y text-base leading-relaxed"
          placeholder="Teach me…"
          aria-describedby="goal-help"
        />

        <p id="goal-help" className="mt-2 text-sm text-muted-foreground">
          Say what level you want: &ldquo;from scratch&rdquo;,
          &ldquo;intermediate&rdquo;, &ldquo;I already know the basics&rdquo;. It
          changes how the notes are written.
        </p>

        {!goal.trim() ? (
          <div className="mt-4">
            <p className="text-sm text-muted-foreground">Or start from one of these:</p>
            <ul className="mt-2 flex flex-wrap gap-2">
              {EXAMPLES.map((example) => (
                <li key={example}>
                  <button
                    type="button"
                    onClick={() => onGoalChange(example)}
                    className={cn(
                      "rounded-full border border-border bg-background px-3 py-1.5 text-left text-sm text-foreground/75",
                      "transition-colors duration-150 hover:border-primary/40 hover:bg-primary/5 hover:text-foreground",
                      "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
                    )}
                  >
                    {example}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        <details className="group mt-5 border-t border-border/70 pt-4">
          <summary
            className={cn(
              "flex cursor-pointer list-none items-center gap-2 text-sm text-foreground/75",
              "hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
              "[&::-webkit-details-marker]:hidden",
            )}
          >
            <span
              aria-hidden="true"
              className="inline-block transition-transform duration-150 ease-out group-open:rotate-90 motion-reduce:transition-none"
            >
              ›
            </span>
            <span className="font-medium">Options</span>
            <span className="text-muted-foreground">
              {optionSummary.length
                ? `· ${optionSummary.join(", ")}`
                : "· nothing extra"}
            </span>
          </summary>

          <div className="mt-4 space-y-4 pl-5">
            <div className="flex items-start gap-2.5">
              <Checkbox
                id="quiz"
                checked={withQuiz}
                onCheckedChange={(v) => onQuizChange(v === true)}
                className="mt-0.5"
              />
              <Label htmlFor="quiz" className="text-sm font-normal">
                Add practice questions
                <span className="mt-0.5 block text-muted-foreground">
                  A few questions per section, answerable from the sources.
                  Roughly doubles the cost.
                </span>
              </Label>
            </div>

            {hasStyle ? (
              <div className="flex items-start gap-2.5">
                <Checkbox
                  id="style"
                  checked={useStyle}
                  onCheckedChange={(v) => onStyleChange(v === true)}
                  className="mt-0.5"
                />
                <Label htmlFor="style" className="text-sm font-normal">
                  Write in my style
                  <span className="mt-0.5 block text-muted-foreground">
                    Easier to read, slightly less strictly grounded.
                  </span>
                </Label>
              </div>
            ) : null}

            {uploads.length > 0 ? (
              <div>
                <Label htmlFor="source" className="text-sm font-normal">
                  Where the notes come from
                </Label>
                <Select value={sourceMode} onValueChange={onSourceChange}>
                  <SelectTrigger id="source" className="mt-2">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={autoSourceValue}>
                      Find sources for me
                    </SelectItem>
                    {uploads.map((ns) => (
                      <SelectItem key={ns.namespace} value={ns.namespace}>
                        My material: {ns.namespace.replace(`user-${userId}-`, "")}{" "}
                        ({ns.documents} file{ns.documents === 1 ? "" : "s"})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                Sources come from Wikipedia and arXiv. To study from your own
                PDFs,{" "}
                <Link
                  href="/upload"
                  className="font-medium text-primary underline-offset-4 hover:underline"
                >
                  add them under Materials
                </Link>
                .
              </p>
            )}
          </div>
        </details>

        <details className="group mt-3 border-t border-border/70 pt-4">
          <summary
            className={cn(
              "flex cursor-pointer list-none items-center gap-2 text-sm text-foreground/75",
              "hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
              "[&::-webkit-details-marker]:hidden",
            )}
          >
            <span
              aria-hidden="true"
              className="inline-block transition-transform duration-150 ease-out group-open:rotate-90 motion-reduce:transition-none"
            >
              ›
            </span>
            <span className="font-medium">How it is written</span>
            <span className="text-muted-foreground">
              {chosen
                ? `· ${chosen} choice${chosen === 1 ? "" : "s"} set`
                : "· let the writer decide"}
            </span>
          </summary>

          <div className="mt-4 space-y-3 pl-5">
            <Choice
              label="Level"
              value={prefs.level}
              onChange={(v) => set("level", v)}
              options={[
                { value: "beginner", label: "Beginner" },
                { value: "intermediate", label: "Intermediate" },
                { value: "advanced", label: "Advanced" },
              ]}
            />
            <Choice
              label="Language"
              value={prefs.vocabulary}
              onChange={(v) => set("vocabulary", v)}
              options={[
                { value: "plain", label: "Plain English" },
                { value: "mixed", label: "Mixed" },
                { value: "technical", label: "Technical" },
              ]}
            />
            <Choice
              label="Length"
              value={prefs.depth}
              onChange={(v) => set("depth", v)}
              options={[
                { value: "brief", label: "Brief" },
                { value: "standard", label: "Standard" },
                { value: "thorough", label: "Thorough" },
              ]}
            />
            <Choice
              label="Layout"
              value={prefs.structure}
              onChange={(v) => set("structure", v)}
              options={[
                { value: "prose", label: "Prose" },
                { value: "mixed", label: "Mixed" },
                { value: "bullets", label: "Bullets" },
              ]}
            />
            <Choice
              label="Worked examples"
              value={prefs.examples}
              onChange={(v) => set("examples", v)}
              options={YES_NO}
            />
            <Choice
              label="Formulas and notation"
              value={prefs.formulas}
              onChange={(v) => set("formulas", v)}
              options={YES_NO}
            />
            <Choice
              label="Analogies"
              value={prefs.analogies}
              onChange={(v) => set("analogies", v)}
              options={YES_NO}
            />
            <Choice
              label="Diagrams"
              value={prefs.diagrams}
              onChange={(v) => set("diagrams", v)}
              options={[
                { value: "prefer", label: "Where they fit" },
                { value: "avoid", label: "None" },
              ]}
            />

            <p className="pt-1 text-sm text-muted-foreground">
              These change how the notes read, never what they claim. Examples,
              formulas and analogies are drawn from the sources when the sources
              have them, and left out when they do not.
            </p>
          </div>
        </details>

        <div className="mt-6 flex flex-wrap items-center gap-x-4 gap-y-2">
          <Button
            onClick={onSubmit}
            disabled={!goal.trim()}
            size="lg"
            className="w-full sm:w-auto"
          >
            Build my course
          </Button>
          <p className="text-sm text-muted-foreground">
            About a minute. You can leave and it keeps writing.
          </p>
        </div>
      </div>
    </section>
  );
}
