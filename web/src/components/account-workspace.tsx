"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { changePassword, setAccountName, signOut } from "@/lib/api";
import { useSession } from "@/lib/session";

/**
 * The account: the few things a person needs to do to their own login.
 *
 * Changing a password ends every session, this one included, so the page says
 * so before the button rather than surprising someone into signing in again.
 */
export function AccountWorkspace() {
  const { account, loading, setAccount } = useSession();
  const router = useRouter();

  const [name, setName] = useState(account?.display_name ?? "");
  const [nameBusy, setNameBusy] = useState(false);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [passwordBusy, setPasswordBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (loading) {
    return (
      <div className="mx-auto w-full max-w-lg px-4 py-16 sm:px-6">
        <p role="status" className="text-sm text-muted-foreground">
          Checking your session…
        </p>
      </div>
    );
  }

  if (!account) {
    return (
      <div className="mx-auto w-full max-w-lg px-4 py-16 sm:px-6">
        <h1 className="font-heading text-3xl tracking-tight text-ink">Account</h1>
        <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
          You are using NoteKit without an account, so your courses live in this
          browser only.
        </p>
        <div className="mt-6 flex gap-3">
          <Button asChild>
            <Link href="/register">Create an account</Link>
          </Button>
          <Button asChild variant="outline">
            <Link href="/signin">Sign in</Link>
          </Button>
        </div>
      </div>
    );
  }

  async function saveName(event: React.FormEvent) {
    event.preventDefault();
    setNameBusy(true);
    try {
      await setAccountName(name);
      setAccount({ ...account!, display_name: name.trim() });
      toast.success("Name saved");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    } finally {
      setNameBusy(false);
    }
  }

  async function savePassword(event: React.FormEvent) {
    event.preventDefault();
    if (next.length < 10 || passwordBusy) return;
    setPasswordBusy(true);
    setError(null);
    try {
      await changePassword(current, next);
      setAccount(null);
      toast.success("Password changed. Sign in again with the new one.");
      router.push("/signin");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPasswordBusy(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-lg px-4 py-12 sm:px-6">
      <h1 className="font-heading text-3xl tracking-tight text-ink">Account</h1>
      <p className="mt-2 text-sm text-muted-foreground">{account.email}</p>

      <form onSubmit={saveName} className="mt-10 border-t border-border/70 pt-6">
        <h2 className="text-base font-medium text-ink">Your name</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Used to greet you. Nothing else sees it.
        </p>
        <div className="mt-3 flex gap-2">
          <Label htmlFor="display-name" className="sr-only">
            Your name
          </Label>
          <Input
            id="display-name"
            value={name}
            placeholder="Optional"
            onChange={(e) => setName(e.target.value)}
          />
          <Button type="submit" variant="outline" disabled={nameBusy}>
            Save
          </Button>
        </div>
      </form>

      <form onSubmit={savePassword} className="mt-10 border-t border-border/70 pt-6">
        <h2 className="text-base font-medium text-ink">Change your password</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          This signs you out on every device, including this one.
        </p>
        <div className="mt-3 space-y-3">
          <div>
            <Label htmlFor="current">Current password</Label>
            <Input
              id="current"
              type="password"
              autoComplete="current-password"
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
              className="mt-1.5"
            />
          </div>
          <div>
            <Label htmlFor="next">New password</Label>
            <Input
              id="next"
              type="password"
              autoComplete="new-password"
              value={next}
              onChange={(e) => setNext(e.target.value)}
              aria-describedby="next-help"
              className="mt-1.5"
            />
            <p id="next-help" className="mt-1.5 text-xs text-muted-foreground">
              At least 10 characters.
            </p>
          </div>
          {error ? (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          ) : null}
          <Button type="submit" disabled={!current || next.length < 10 || passwordBusy}>
            {passwordBusy ? "Saving…" : "Change password"}
          </Button>
        </div>
      </form>

      <div className="mt-10 border-t border-border/70 pt-6">
        <Button
          type="button"
          variant="ghost"
          className="px-0 text-muted-foreground hover:text-foreground"
          onClick={async () => {
            await signOut();
            setAccount(null);
            router.push("/");
          }}
        >
          Sign out
        </Button>
      </div>
    </div>
  );
}
