"use client";

import Link from "next/link";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { requestPasswordReset } from "@/lib/api";

/**
 * Asking for a reset link.
 *
 * The reply is the same for an address with an account and one without, which
 * is the point: anything else turns this page into a way to find out who has
 * an account here. That means the success message has to be worded as a
 * conditional rather than a promise.
 */
export function ForgotForm() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!email.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      setSent(await requestPasswordReset(email.trim()));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-sm px-4 py-16 sm:px-6">
      <h1 className="font-heading text-3xl tracking-tight text-ink">
        Reset your password
      </h1>

      {sent ? (
        <div role="status" className="mt-6 space-y-4">
          <p className="text-sm leading-relaxed text-foreground/80">{sent}</p>
          <p className="text-sm text-muted-foreground">
            Nothing arrived? Check spam, then{" "}
            <button
              type="button"
              onClick={() => setSent(null)}
              className="font-medium text-primary underline-offset-4 hover:underline"
            >
              try another address
            </button>
            .
          </p>
        </div>
      ) : (
        <>
          <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
            Enter the address on your account and we will send a link that
            works once.
          </p>
          <form onSubmit={submit} className="mt-8 space-y-4" noValidate>
            <div>
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                required
                autoFocus
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="mt-1.5"
              />
            </div>
            {error ? (
              <p role="alert" className="text-sm text-destructive">
                {error}
              </p>
            ) : null}
            <Button
              type="submit"
              size="lg"
              className="w-full"
              disabled={!email.trim() || busy}
            >
              {busy ? "Sending…" : "Send the link"}
            </Button>
          </form>
        </>
      )}

      <p className="mt-8 border-t border-border/70 pt-5 text-sm text-muted-foreground">
        <Link href="/signin" className="underline-offset-4 hover:underline">
          Back to sign in
        </Link>
      </p>
    </div>
  );
}
