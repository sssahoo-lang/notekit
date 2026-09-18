"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { registerAccount, signIn } from "@/lib/api";
import { useSession } from "@/lib/session";

/**
 * Sign in and sign up, which are the same form with different words.
 *
 * Two things are worth noticing. Courses built before signing up are carried
 * across, so making an account never looks like starting over; the browser ids
 * this device has used are sent with the request and their courses move to the
 * account. And the password rule is stated up front rather than after a failed
 * attempt, because a rule you meet first time is not an error message.
 */

type Mode = "signin" | "register";

const COPY = {
  signin: {
    title: "Sign in",
    blurb: "Your courses, on any machine you use.",
    action: "Sign in",
    swapText: "New here?",
    swapLabel: "Create an account",
    swapHref: "/register",
  },
  register: {
    title: "Create an account",
    blurb:
      "Keeps your courses when this browser forgets you, and brings them to your other devices.",
    action: "Create account",
    swapText: "Already have one?",
    swapLabel: "Sign in",
    swapHref: "/signin",
  },
} as const;

export function AuthForm({ mode }: { mode: Mode }) {
  const copy = COPY[mode];
  const router = useRouter();
  const { claim, setAccount } = useSession();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const tooShort = mode === "register" && password.length > 0 && password.length < 10;
  const canSubmit = email.trim() && password.length >= (mode === "register" ? 10 : 1);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!canSubmit || busy) return;
    setBusy(true);
    setError(null);
    try {
      const account =
        mode === "register"
          ? await registerAccount({
              email: email.trim(),
              password,
              display_name: name.trim(),
              claim,
            })
          : await signIn({ email: email.trim(), password, claim });
      setAccount(account);
      toast.success(
        mode === "register" ? "Account created" : `Signed in as ${account.email}`,
      );
      router.push("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div id="main" className="mx-auto w-full max-w-sm px-4 py-16 sm:px-6">
      <h1 className="font-heading text-3xl tracking-tight text-ink">{copy.title}</h1>
      <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{copy.blurb}</p>

      <form onSubmit={submit} className="mt-8 space-y-4" noValidate>
        {mode === "register" ? (
          <div>
            <Label htmlFor="name">Your name</Label>
            <Input
              id="name"
              value={name}
              autoComplete="name"
              placeholder="Optional"
              onChange={(e) => setName(e.target.value)}
              className="mt-1.5"
            />
          </div>
        ) : null}

        <div>
          <Label htmlFor="email">Email</Label>
          <Input
            id="email"
            type="email"
            required
            autoFocus={mode === "signin"}
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="mt-1.5"
          />
        </div>

        <div>
          <Label htmlFor="password">Password</Label>
          <Input
            id="password"
            type="password"
            required
            autoComplete={mode === "register" ? "new-password" : "current-password"}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            aria-describedby={mode === "register" ? "password-help" : undefined}
            aria-invalid={tooShort || undefined}
            className="mt-1.5"
          />
          {mode === "register" ? (
            <p id="password-help" className="mt-1.5 text-xs text-muted-foreground">
              At least 10 characters. A short phrase you will remember beats a
              short word you will not.
            </p>
          ) : null}
        </div>

        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}

        <Button type="submit" size="lg" className="w-full" disabled={!canSubmit || busy}>
          {busy ? "One moment…" : copy.action}
        </Button>
      </form>

      {mode === "register" && claim.length ? (
        <p className="mt-4 text-xs text-muted-foreground">
          Courses you have already built on this browser will move to your
          account.
        </p>
      ) : null}

      <p className="mt-8 border-t border-border/70 pt-5 text-sm text-muted-foreground">
        {copy.swapText}{" "}
        <Link
          href={copy.swapHref}
          className="font-medium text-primary underline-offset-4 hover:underline"
        >
          {copy.swapLabel}
        </Link>
      </p>
      <p className="mt-2 text-sm text-muted-foreground">
        Or{" "}
        <Link href="/" className="underline-offset-4 hover:underline">
          keep using it without an account
        </Link>
        . Your courses stay in this browser.
      </p>
    </div>
  );
}
