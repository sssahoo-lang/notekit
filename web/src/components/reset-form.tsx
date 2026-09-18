"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { resetPassword } from "@/lib/api";

/**
 * Choosing a new password from a link.
 *
 * The token stays in the URL and is never stored: the page is a single use of
 * it. Setting a password here signs out every device, which is the point of
 * resetting one rather than changing it.
 */
export function ResetForm() {
  const params = useSearchParams();
  const router = useRouter();
  const token = params.get("token") ?? "";

  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const tooShort = password.length > 0 && password.length < 10;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (password.length < 10 || busy) return;
    setBusy(true);
    setError(null);
    try {
      await resetPassword(token, password);
      toast.success("Password changed. Sign in with the new one.");
      router.push("/signin");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  if (!token) {
    return (
      <div className="mx-auto w-full max-w-sm px-4 py-16 sm:px-6">
        <h1 className="font-heading text-3xl tracking-tight text-ink">
          That link is incomplete
        </h1>
        <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
          Open the link from your email, or{" "}
          <Link href="/forgot" className="font-medium text-primary underline-offset-4 hover:underline">
            ask for a new one
          </Link>
          .
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-sm px-4 py-16 sm:px-6">
      <h1 className="font-heading text-3xl tracking-tight text-ink">
        Choose a new password
      </h1>
      <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
        This signs you out everywhere, including any device you no longer have.
      </p>

      <form onSubmit={submit} className="mt-8 space-y-4" noValidate>
        <div>
          <Label htmlFor="password">New password</Label>
          <Input
            id="password"
            type="password"
            required
            autoFocus
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            aria-describedby="password-help"
            aria-invalid={tooShort || undefined}
            className="mt-1.5"
          />
          <p id="password-help" className="mt-1.5 text-xs text-muted-foreground">
            At least 10 characters.
          </p>
        </div>
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
        <Button type="submit" size="lg" className="w-full" disabled={password.length < 10 || busy}>
          {busy ? "Saving…" : "Set the password"}
        </Button>
      </form>
    </div>
  );
}
