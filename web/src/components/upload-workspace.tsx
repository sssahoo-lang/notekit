"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";

import { RunError } from "@/components/run-status";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { uploadFiles } from "@/lib/api";
import { getProfile, type Profile } from "@/lib/profile";

export function UploadWorkspace() {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [topic, setTopic] = useState("notes");
  const [files, setFiles] = useState<FileList | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [skipped, setSkipped] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setProfile(getProfile());
  }, []);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!files?.length) {
      toast.error("Choose at least one PDF, text, or markdown file");
      return;
    }

    setBusy(true);
    setResult(null);
    setSkipped([]);
    setError(null);
    try {
      const summary = await uploadFiles(
        profile?.id ?? "anonymous",
        topic.trim() || "notes",
        Array.from(files),
      );
      const docs = (summary.new_documents as number) ?? 0;
      const chunks = (summary.new_chunks as number) ?? 0;
      const skippedList = Array.isArray(summary.skipped)
        ? (summary.skipped as string[])
        : [];
      setSkipped(skippedList);
      setResult(
        `Added ${docs} file${docs === 1 ? "" : "s"} to your material — ` +
          `${chunks} passages your notes can be written from.`,
      );
      toast.success("Your material is ready to study from");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div id="main" className="mx-auto w-full max-w-2xl px-4 py-12 sm:px-6">
      <h1 className="font-heading text-3xl tracking-tight text-ink">
        Your material
      </h1>
      <p className="mt-2 max-w-prose text-muted-foreground">
        Add your own lecture notes, slides, or textbook chapters. Courses built
        from them use only your files, so every claim traces back to something
        you provided. Only you can see what you upload.
      </p>

      <form onSubmit={onSubmit} className="mt-8 space-y-5">
        <div className="space-y-2">
          <Label htmlFor="topic">What is this material about?</Label>
          <Input
            id="topic"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            placeholder="e.g. machine learning"
            disabled={busy}
            aria-describedby="topic-help"
          />
          <p id="topic-help" className="text-sm text-muted-foreground">
            Keeps separate subjects apart, so a biology course doesn&apos;t pull
            from your history notes.
          </p>
        </div>

        <div className="space-y-2">
          <Label htmlFor="files">Files</Label>
          <Input
            id="files"
            type="file"
            multiple
            accept=".pdf,.txt,.md,text/plain,application/pdf"
            onChange={(e) => setFiles(e.target.files)}
            disabled={busy}
            className="cursor-pointer file:mr-3"
            aria-describedby="files-help"
          />
          <p id="files-help" className="text-sm text-muted-foreground">
            PDFs, plain text, and markdown. Scanned PDFs with no selectable text
            can&apos;t be read yet — you&apos;ll be told which were skipped.
          </p>
        </div>

        <Button type="submit" disabled={busy}>
          {busy ? "Reading your files…" : "Add material"}
        </Button>
        {busy ? (
          <p
            role="status"
            aria-live="polite"
            className="text-sm text-muted-foreground"
          >
            Reading and indexing. Large PDFs take a few seconds each.
          </p>
        ) : null}
      </form>

      {error ? (
        <div className="mt-6">
          <RunError message={error} />
        </div>
      ) : null}

      {result ? (
        <div
          role="status"
          className="mt-8 rounded-xl border border-teal-800/25 bg-teal-50 px-4 py-3"
        >
          <p className="text-sm text-teal-950">{result}</p>
          {skipped.length ? (
            <details className="mt-2">
              <summary className="cursor-pointer text-sm text-teal-900">
                {skipped.length} file{skipped.length === 1 ? "" : "s"} skipped
              </summary>
              <ul className="mt-1 space-y-1 text-sm text-teal-900">
                {skipped.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
            </details>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
