"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { getStyle, learnStyle } from "@/lib/api";
import type { StyleProfile } from "@/lib/types";
import { getStoredUser, setStoredUser } from "@/lib/user";

export function StyleWorkspace() {
  const [user, setUser] = useState("");
  const [sample, setSample] = useState("");
  const [profile, setProfile] = useState<StyleProfile | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.resolve().then(() => {
      if (cancelled) return;
      const stored = getStoredUser();
      setUser(stored);
      if (stored) void load(stored);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  async function load(who: string) {
    setLoading(true);
    try {
      setProfile(await getStyle(who));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  async function onLearn(e: React.FormEvent) {
    e.preventDefault();
    if (!user.trim()) {
      toast.error("User id is required");
      return;
    }
    if (sample.trim().length < 40) {
      toast.error("Paste a longer writing sample");
      return;
    }
    setStoredUser(user);
    setBusy(true);
    try {
      const learned = await learnStyle(user.trim(), sample.trim());
      setProfile(learned);
      toast.success("Style profile saved");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-2xl px-4 py-14 sm:px-6">
      <p className="font-mono text-[0.7rem] tracking-[0.18em] text-primary/80 uppercase">
        Voice, not content
      </p>
      <h1 className="font-heading mt-3 text-4xl tracking-tight text-ink">
        Style
      </h1>
      <p className="mt-3 max-w-lg text-muted-foreground">
        Learn how you write from a sample, then apply that form to any course.
        Costs about 10 points of faithfulness — leave it off unless you want
        the voice trade-off.
      </p>

      <form onSubmit={onLearn} className="mt-10 space-y-5">
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-[12rem] flex-1 space-y-2">
            <Label htmlFor="user">User id</Label>
            <Input
              id="user"
              value={user}
              onChange={(e) => setUser(e.target.value)}
              placeholder="sriya"
              disabled={busy}
            />
          </div>
          <Button
            type="button"
            variant="secondary"
            disabled={!user.trim() || loading || busy}
            onClick={() => {
              setStoredUser(user);
              void load(user.trim());
            }}
          >
            {loading ? "Loading…" : "Load profile"}
          </Button>
        </div>

        <div className="space-y-2">
          <Label htmlFor="sample">Writing sample</Label>
          <Textarea
            id="sample"
            value={sample}
            onChange={(e) => setSample(e.target.value)}
            rows={10}
            placeholder="Paste a few paragraphs of your own writing…"
            className="resize-y font-notes"
            disabled={busy}
          />
        </div>

        <Button type="submit" disabled={busy}>
          {busy ? "Learning…" : "Learn style"}
        </Button>
      </form>

      {profile ? (
        <div className="mt-10 space-y-4 rounded-2xl border border-border/70 bg-paper px-5 py-6">
          <h2 className="font-heading text-xl tracking-tight">Saved profile</h2>
          <p className="text-sm leading-relaxed text-ink/85">{profile.summary}</p>
          <div className="flex flex-wrap gap-2">
            <Badge variant="secondary">{profile.formality}</Badge>
            <Badge variant="secondary">{profile.person} person</Badge>
            <Badge variant="secondary">{profile.sentence_length} sentences</Badge>
            <Badge variant="secondary">{profile.structure}</Badge>
            <Badge variant="secondary">{profile.vocabulary}</Badge>
            {profile.uses_analogies ? (
              <Badge variant="outline">analogies</Badge>
            ) : null}
            {profile.uses_worked_examples ? (
              <Badge variant="outline">worked examples</Badge>
            ) : null}
            {profile.uses_notation ? (
              <Badge variant="outline">notation</Badge>
            ) : null}
          </div>
          {profile.signature_habits.length ? (
            <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
              {profile.signature_habits.map((h) => (
                <li key={h}>{h}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
