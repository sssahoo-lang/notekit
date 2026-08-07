"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";

import { RunError } from "@/components/run-status";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { getStyle, learnStyle } from "@/lib/api";
import { getProfile } from "@/lib/profile";
import type { StyleProfile } from "@/lib/types";

export function StyleWorkspace() {
  const [userId, setUserId] = useState<string | null>(null);
  const [sample, setSample] = useState("");
  const [profile, setProfile] = useState<StyleProfile | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // See upload-workspace.tsx: getProfile() must run post-hydration, not in
    // a lazy initializer, or the server's "anonymous" stub and the client's
    // real profile disagree on first paint.
    const id = getProfile().id;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setUserId(id);
    getStyle(id)
      .then(setProfile)
      .catch(() => setProfile(null))
      .finally(() => setLoading(false));
  }, []);

  async function onLearn(e: React.FormEvent) {
    e.preventDefault();
    if (sample.trim().length < 400) {
      toast.error(
        "Paste a bit more — a few paragraphs, so there's enough to go on",
      );
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setProfile(await learnStyle(userId ?? "anonymous", sample.trim()));
      toast.success("Saved. New courses can now use your style.");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div id="main" className="mx-auto w-full max-w-2xl px-4 py-12 sm:px-6">
      <h1 className="font-heading text-3xl tracking-tight text-ink">
        Writing style
      </h1>
      <p className="mt-2 max-w-prose text-muted-foreground">
        Paste something you wrote and NoteKit learns how you write — sentence
        length, formality, analogies. New courses can then use that voice.
      </p>

      <div className="mt-4 rounded-xl border border-amber-800/20 bg-amber-50/70 p-4">
        <p className="text-sm text-amber-950">
          <strong className="font-medium">Worth knowing:</strong> notes in your
          style are a bit less strictly grounded — roughly 10% more claims stray
          via analogies. The option only appears on Study after you save a
          profile here.
        </p>
      </div>

      <p className="mt-4 text-sm text-muted-foreground">
        Only a description of your writing is kept. The sample is used once and
        never stored.
      </p>

      <form
        onSubmit={onLearn}
        className="mt-8 space-y-4 rounded-2xl border border-border/80 bg-card/90 p-5 sm:p-6"
      >
        <div className="space-y-2">
          <Label htmlFor="sample">Something you wrote</Label>
          <Textarea
            id="sample"
            value={sample}
            onChange={(e) => setSample(e.target.value)}
            rows={10}
            placeholder="Paste a few paragraphs — an old essay, notes, a blog post. Anything in your own words."
            className="resize-y font-notes text-base"
            disabled={busy}
            aria-describedby="sample-help"
          />
          <p id="sample-help" className="text-sm text-muted-foreground">
            {sample.trim().length < 400
              ? `About ${Math.max(0, 400 - sample.trim().length)} more characters needed.`
              : "Long enough — ready when you are."}
          </p>
        </div>

        <Button type="submit" disabled={busy || sample.trim().length < 400}>
          {busy ? "Reading your writing…" : "Learn my style"}
        </Button>
      </form>

      {error ? (
        <div className="mt-6">
          <RunError message={error} />
        </div>
      ) : null}

      {loading ? (
        <p className="mt-8 text-sm text-muted-foreground">Checking…</p>
      ) : profile ? (
        <section
          aria-labelledby="saved-style"
          className="mt-10 space-y-4 rounded-2xl border border-border bg-card px-5 py-6"
        >
          <h2 id="saved-style" className="text-lg font-medium text-ink">
            How NoteKit sees your writing
          </h2>
          <p className="leading-relaxed text-foreground/85">{profile.summary}</p>
          <div className="flex flex-wrap gap-2">
            <Badge variant="secondary">{profile.formality}</Badge>
            <Badge variant="secondary">{profile.person} person</Badge>
            <Badge variant="secondary">
              {profile.sentence_length} sentences
            </Badge>
            <Badge variant="secondary">{profile.structure}</Badge>
            <Badge variant="secondary">{profile.vocabulary} words</Badge>
            {profile.uses_analogies ? (
              <Badge variant="outline">uses analogies</Badge>
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
        </section>
      ) : (
        <p className="mt-8 max-w-prose text-sm text-muted-foreground">
          No style saved yet. Once you add one it appears here, and a
          &ldquo;Write in my style&rdquo; option shows up when you build a
          course.
        </p>
      )}
    </div>
  );
}
