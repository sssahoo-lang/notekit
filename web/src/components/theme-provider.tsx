"use client";

import { ThemeProvider as NextThemes } from "next-themes";

/**
 * next-themes needs a client boundary, and the app shell is a Server
 * Component, so the provider lives here rather than in layout.tsx.
 *
 * `attribute="class"` because the Tailwind v4 dark variant in globals.css is
 * declared as `&:is(.dark *)` — it looks for a class, not a data attribute.
 */
export function ThemeProvider({ children }: { children: React.ReactNode }) {
  return (
    <NextThemes
      attribute="class"
      defaultTheme="system"
      enableSystem
      disableTransitionOnChange
    >
      {children}
    </NextThemes>
  );
}
