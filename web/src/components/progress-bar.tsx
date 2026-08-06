import { cn } from "@/lib/utils";

/**
 * A progress bar that animates without forcing layout.
 *
 * The obvious implementation animates `width`, which makes the browser
 * recalculate layout on every frame. Scaling along X is composited instead, so
 * the fill moves on the GPU and cannot cause jank in the prose beside it.
 * `origin-left` keeps it growing from the correct edge.
 */
export function ProgressBar({
  value,
  max,
  label,
  className,
  barClassName,
}: {
  value: number;
  max: number;
  label: string;
  className?: string;
  barClassName?: string;
}) {
  const ratio = max > 0 ? Math.min(Math.max(value / max, 0), 1) : 0;

  return (
    <div
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={max}
      aria-valuenow={value}
      aria-label={label}
      className={cn("h-1.5 overflow-hidden rounded-full bg-muted", className)}
    >
      <div
        className={cn(
          "h-full w-full origin-left rounded-full bg-primary",
          "transition-transform duration-300 ease-out motion-reduce:transition-none",
          barClassName,
        )}
        style={{ transform: `scaleX(${ratio})` }}
      />
    </div>
  );
}
