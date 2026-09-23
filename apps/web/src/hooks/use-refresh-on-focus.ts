"use client";

import { useEffect, useRef } from "react";

/**
 * Re-run `refresh` when the user returns to the page.
 *
 * Client pages that fetch in a mount-effect go stale as soon as the data
 * changes somewhere else — another tab, or a mutation on a different route
 * that the user navigates back from (Next's Router Cache can serve the cached
 * entry without remounting). Listening for focus and `visibilitychange`
 * covers both.
 *
 * @param refresh   Called when the page regains focus. Kept in a ref so the
 *                  listeners are attached once, not on every render.
 * @param enabled   Skip while the page has nothing to refresh (e.g. signed out).
 * @param minIntervalMs Ignore bursts — focus and visibilitychange often fire
 *                  together, and tab-switching should not hammer the API.
 */
export function useRefreshOnFocus(
  refresh: () => void,
  { enabled = true, minIntervalMs = 5_000 }: { enabled?: boolean; minIntervalMs?: number } = {},
): void {
  const refreshRef = useRef(refresh);
  const lastRunRef = useRef(0);

  useEffect(() => {
    refreshRef.current = refresh;
  }, [refresh]);

  useEffect(() => {
    if (!enabled || typeof window === "undefined") return;

    const run = () => {
      if (document.visibilityState === "hidden") return;
      const now = Date.now();
      if (now - lastRunRef.current < minIntervalMs) return;
      lastRunRef.current = now;
      refreshRef.current();
    };

    window.addEventListener("focus", run);
    document.addEventListener("visibilitychange", run);
    return () => {
      window.removeEventListener("focus", run);
      document.removeEventListener("visibilitychange", run);
    };
  }, [enabled, minIntervalMs]);
}
