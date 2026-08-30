"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { SiteAuthError, gateStatus, unlock } from "@/lib/api";

/**
 * The password screen for the deployed demo.
 *
 * Deliberately not a login: there is one password, everyone who enters shares
 * one identity, and nothing behind it is private from anyone else inside. It
 * exists so the public URL is not an open upload form pointed at a paid API
 * key.
 *
 * Three states rather than two. "Checking" renders nothing at all: flashing a
 * password box at someone running locally, where the gate is off, would be a
 * worse bug than a moment of blank screen. Only a server that says it is gated
 * ever produces a prompt.
 */

type Phase = "checking" | "locked" | "open" | "unreachable";

export function SiteGate({ children }: { children: React.ReactNode }) {
  const [phase, setPhase] = useState<Phase>("checking");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    // Guarded because the check outlives a fast unmount in dev's double-invoke.
    let cancelled = false;

    gateStatus()
      .then(({ required, unlocked }) => {
        if (!cancelled) setPhase(!required || unlocked ? "open" : "locked");
      })
      .catch(() => {
        // The API being down is not the same as being locked out, and asking
        // for a password that cannot be checked would waste the reader's time.
        // The app's own error states handle a dead backend better than this
        // screen can.
        if (!cancelled) setPhase("unreachable");
      });

    return () => {
      cancelled = true;
    };
  }, []);

  async function submit(event?: React.FormEvent) {
    event?.preventDefault();
    if (!password.trim() || submitting) return;

    setSubmitting(true);
    setError(null);
    try {
      await unlock(password);
      setPassword("");
      setPhase("open");
    } catch (err) {
      setError(
        err instanceof SiteAuthError
          ? err.message
          : "Could not reach the server. Try again in a moment.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  if (phase === "checking") return null;
  if (phase === "open" || phase === "unreachable") return <>{children}</>;

  return (
    <div className="flex min-h-screen items-center justify-center px-6 py-16">
      <div className="w-full max-w-sm">
        <h1 className="font-heading text-3xl tracking-tight">NoteKit</h1>
        <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
          This demo is password protected, because it runs against a live API
          key. Enter the password you were given to continue.
        </p>

        <form onSubmit={submit} className="mt-8 space-y-3">
          <Label htmlFor="site-password" className="text-sm">
            Password
          </Label>
          <Input
            id="site-password"
            type="password"
            autoFocus
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            // Enter submits explicitly rather than leaning on the form's
            // implicit submission. Belt and braces for the one key everybody
            // actually uses on a password field.
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                void submit();
              }
            }}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? "site-password-error" : undefined}
          />
          {error ? (
            <p
              id="site-password-error"
              role="alert"
              className="text-sm text-destructive"
            >
              {error}
            </p>
          ) : null}
          <Button
            type="submit"
            className="w-full"
            disabled={!password.trim() || submitting}
          >
            {submitting ? "Checking…" : "Enter"}
          </Button>
        </form>
      </div>
    </div>
  );
}
