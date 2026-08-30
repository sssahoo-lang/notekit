"use client";

// lucide, not Phosphor: the project already depends on lucide-react and
// mixing icon families in one tree is worse than the library choice.
import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";

/**
 * Light / dark switch.
 *
 * The icon can only be chosen once the client knows the resolved theme, and on
 * the server it does not. Rendering a fixed placeholder until mount keeps the
 * server and client markup identical; swapping the icon during hydration would
 * be a mismatch.
 */
export function ThemeToggle({ className }: { className?: string }) {
  const { resolvedTheme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    // The mount flag has to be set after hydration, which is the whole point:
    // the server cannot know the resolved theme, so the first client render
    // must match the server's markup and only then swap the icon.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setMounted(true);
  }, []);

  const isDark = resolvedTheme === "dark";

  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      className={className}
      aria-label={
        mounted
          ? `Switch to ${isDark ? "light" : "dark"} theme`
          : "Switch theme"
      }
      onClick={() => setTheme(isDark ? "light" : "dark")}
    >
      {mounted && isDark ? (
        <Moon className="size-4" aria-hidden />
      ) : (
        <Sun className="size-4" aria-hidden />
      )}
    </Button>
  );
}
