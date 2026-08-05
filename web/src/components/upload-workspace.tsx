"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { uploadFiles } from "@/lib/api";
import { getStoredUser, setStoredUser } from "@/lib/user";

export function UploadWorkspace() {
  const [user, setUser] = useState("");
  const [topic, setTopic] = useState("notes");
  const [files, setFiles] = useState<FileList | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.resolve().then(() => {
      if (!cancelled) setUser(getStoredUser());
    });
    return () => {
      cancelled = true;
    };
  }, []);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!user.trim()) {
      toast.error("User id is required");
      return;
    }
    if (!files?.length) {
      toast.error("Choose at least one PDF, .txt, or .md file");
      return;
    }

    setStoredUser(user);
    setBusy(true);
    setResult(null);
    try {
      const summary = await uploadFiles(
        user.trim(),
        topic.trim() || "notes",
        Array.from(files),
      );
      const ns = summary.namespace;
      const docs = summary.new_documents ?? 0;
      const chunks = summary.new_chunks ?? 0;
      const skipped = Array.isArray(summary.skipped)
        ? summary.skipped.length
        : 0;
      setResult(
        `Indexed into ${ns} · ${docs} new documents · ${chunks} chunks` +
          (skipped ? ` · ${skipped} skipped` : ""),
      );
      toast.success(`Uploaded to ${ns}`);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      toast.error(message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-2xl px-4 py-14 sm:px-6">
      <p className="font-mono text-[0.7rem] tracking-[0.18em] text-primary/80 uppercase">
        Your corpus
      </p>
      <h1 className="font-heading mt-3 text-4xl tracking-tight text-ink">
        Upload
      </h1>
      <p className="mt-3 max-w-lg text-muted-foreground">
        Index PDFs, text, or markdown into a per-user namespace. Then generate a
        course against that corpus from the Course page.
      </p>

      <form onSubmit={onSubmit} className="mt-10 space-y-5">
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="user">User id</Label>
            <Input
              id="user"
              value={user}
              onChange={(e) => setUser(e.target.value)}
              placeholder="sriya"
              disabled={busy}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="topic">Topic slug</Label>
            <Input
              id="topic"
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              placeholder="ml"
              disabled={busy}
            />
          </div>
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
          />
          <p className="text-xs text-muted-foreground">
            Namespace becomes{" "}
            <span className="font-mono">
              user-{user.trim() || "…"}-{topic.trim() || "notes"}
            </span>
          </p>
        </div>

        <Button type="submit" disabled={busy}>
          {busy ? "Indexing…" : "Upload & index"}
        </Button>
      </form>

      {result ? (
        <p className="mt-8 rounded-xl border border-teal-700/20 bg-teal-50 px-4 py-3 text-sm text-teal-950">
          {result}
        </p>
      ) : null}
    </div>
  );
}
