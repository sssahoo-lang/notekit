"use client";

import { Button } from "@/components/ui/button";
import type { SavedCourseSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

type Props = {
  items: SavedCourseSummary[];
  activeId: number | null;
  user: string;
  onSelect: (id: number) => void;
  onDelete: (id: number) => void;
  onRefresh: () => void;
};

function formatWhen(iso: string): string {
  try {
    return new Intl.DateTimeFormat(undefined, {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

export function HistoryPanel({
  items,
  activeId,
  user,
  onSelect,
  onDelete,
  onRefresh,
}: Props) {
  return (
    <aside className="rounded-2xl border border-border/70 bg-paper/80 p-4">
      <div className="mb-3 flex items-center justify-between gap-2">
        <div>
          <p className="font-mono text-[0.65rem] tracking-[0.16em] text-muted-foreground uppercase">
            History
          </p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {user.trim() || "anonymous"}
          </p>
        </div>
        <Button type="button" size="sm" variant="ghost" onClick={onRefresh}>
          Refresh
        </Button>
      </div>

      {items.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          Nothing saved yet for this user. Generate a course once — when it
          finishes, it shows up here and reopening won&apos;t re-run or re-bill.
        </p>
      ) : (
        <ul className="max-h-[28rem] space-y-2 overflow-y-auto pr-1">
          {items.map((item) => (
            <li key={item.id}>
              <div
                className={cn(
                  "rounded-xl border px-3 py-2.5 transition-colors",
                  activeId === item.id
                    ? "border-primary/40 bg-primary/5"
                    : "border-border/70 hover:border-primary/25",
                )}
              >
                <button
                  type="button"
                  className="w-full text-left"
                  onClick={() => onSelect(item.id)}
                >
                  <p className="line-clamp-2 text-sm font-medium leading-snug">
                    {item.goal}
                  </p>
                  <p className="mt-1 font-mono text-[0.65rem] text-muted-foreground">
                    {formatWhen(item.created_at)} · {item.module_count} modules
                    {item.estimated_cost_usd != null
                      ? ` · ~$${Number(item.estimated_cost_usd).toFixed(2)}`
                      : ""}
                  </p>
                </button>
                <div className="mt-2 flex justify-end">
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    className="h-7 text-xs text-muted-foreground hover:text-destructive"
                    onClick={() => onDelete(item.id)}
                  >
                    Delete
                  </Button>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
}
