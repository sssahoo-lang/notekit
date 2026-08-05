"use client";

import {
  createContext,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

/**
 * Lets the sidebar open a course that the workspace owns.
 *
 * Courses are workspace state rather than routes, so the sidebar cannot link to
 * one. Rather than refactor generation, resume and claiming onto a router, the
 * two sides share a small context: the sidebar asks for a course, the workspace
 * answers. `refreshToken` runs the other way, so finishing a course tells the
 * sidebar its library is stale.
 */
type CourseNav = {
  requestedCourseId: number | null;
  requestOpen: (id: number) => void;
  clearRequest: () => void;
  goHome: () => void;
  homeToken: number;
  refreshToken: number;
  refreshLibrary: () => void;
};

const Context = createContext<CourseNav | null>(null);

export function CourseNavProvider({ children }: { children: ReactNode }) {
  const [requestedCourseId, setRequested] = useState<number | null>(null);
  const [refreshToken, setRefreshToken] = useState(0);
  const [homeToken, setHomeToken] = useState(0);

  const value = useMemo<CourseNav>(
    () => ({
      requestedCourseId,
      requestOpen: (id: number) => setRequested(id),
      clearRequest: () => setRequested(null),
      goHome: () => setHomeToken((n) => n + 1),
      homeToken,
      refreshToken,
      refreshLibrary: () => setRefreshToken((n) => n + 1),
    }),
    [requestedCourseId, refreshToken, homeToken],
  );

  return <Context.Provider value={value}>{children}</Context.Provider>;
}

const noop = () => undefined;

// Module-level so it is a stable reference and involves no hook call — a hook
// inside this branch would break the rules of hooks.
const DETACHED: CourseNav = {
  requestedCourseId: null,
  requestOpen: noop,
  clearRequest: noop,
  goHome: noop,
  homeToken: 0,
  refreshToken: 0,
  refreshLibrary: noop,
};

export function useCourseNav(): CourseNav {
  // Pages outside the shell should still render rather than crash.
  return useContext(Context) ?? DETACHED;
}
