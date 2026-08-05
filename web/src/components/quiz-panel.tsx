"use client";

import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { Quiz } from "@/lib/types";

import { CitedText } from "./cited-text";

type Props = {
  quiz: Quiz;
  onCite?: (id: number) => void;
};

export function QuizPanel({ quiz, onCite }: Props) {
  const [answers, setAnswers] = useState<Record<number, number>>({});
  const [revealed, setRevealed] = useState<Record<number, boolean>>({});

  if (!quiz.questions.length) return null;

  return (
    <div className="space-y-6">
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="font-heading text-lg tracking-tight">Check yourself</h3>
        <Badge variant="secondary">{quiz.questions.length} questions</Badge>
      </div>
      <ol className="space-y-8">
        {quiz.questions.map((q, qi) => {
          const chosen = answers[qi];
          const show = revealed[qi];
          const correct = chosen === q.answer_index;
          return (
            <li key={qi} className="space-y-3">
              <p className="font-medium leading-snug">
                <span className="mr-2 font-mono text-xs text-muted-foreground">
                  {qi + 1}.
                </span>
                {q.question}
              </p>
              <div className="grid gap-2">
                {q.options.map((opt, oi) => {
                  const selected = chosen === oi;
                  const isAnswer = oi === q.answer_index;
                  return (
                    <button
                      key={oi}
                      type="button"
                      disabled={show}
                      onClick={() => setAnswers((a) => ({ ...a, [qi]: oi }))}
                      className={cn(
                        "rounded-lg border px-3 py-2.5 text-left text-sm transition-colors",
                        !show && selected && "border-primary bg-primary/5",
                        !show && !selected && "border-border hover:border-primary/40",
                        show && isAnswer && "border-teal-700/40 bg-teal-50 text-teal-950",
                        show && selected && !isAnswer && "border-destructive/40 bg-destructive/5",
                        show && !selected && !isAnswer && "opacity-60",
                      )}
                    >
                      <span className="mr-2 font-mono text-xs text-muted-foreground">
                        {String.fromCharCode(65 + oi)}
                      </span>
                      {opt}
                    </button>
                  );
                })}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {!show ? (
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={chosen === undefined}
                    onClick={() => setRevealed((r) => ({ ...r, [qi]: true }))}
                  >
                    Check answer
                  </Button>
                ) : (
                  <Badge variant={correct ? "secondary" : "destructive"}>
                    {correct ? "Correct" : "Not quite"}
                  </Badge>
                )}
              </div>
              {show ? (
                <CitedText
                  text={q.explanation}
                  onCite={onCite}
                  className="rounded-lg bg-muted/60 px-3 py-2 text-sm text-muted-foreground"
                />
              ) : null}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
