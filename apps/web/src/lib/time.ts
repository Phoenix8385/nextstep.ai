/** Small date helpers used by job cards and the detail page. */

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/** "just now", "5 minutes ago", "2 hours ago", "3 days ago", "2 weeks ago", else a date. */
export function relativeTime(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "unknown";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "unknown";
  const diff = now.getTime() - then;
  if (diff < MINUTE) return "just now";
  if (diff < HOUR) return plural(Math.floor(diff / MINUTE), "minute");
  if (diff < DAY) return plural(Math.floor(diff / HOUR), "hour");
  if (diff < 14 * DAY) return plural(Math.floor(diff / DAY), "day");
  if (diff < 60 * DAY) return plural(Math.floor(diff / (7 * DAY)), "week");
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function plural(n: number, unit: string): string {
  return `${n} ${unit}${n === 1 ? "" : "s"} ago`;
}

/** Whole days from `now` until `iso` (negative if past); `null` when there is no deadline. */
export function daysUntil(iso: string | null | undefined, now: Date = new Date()): number | null {
  if (!iso) return null;
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return null;
  return Math.ceil((then - now.getTime()) / DAY);
}

/** "Closes today", "Closes tomorrow", "Closes in 5 days", or "Closed" — `null` outside the window. */
export function deadlineLabel(
  iso: string | null | undefined,
  { withinDays = 7, now = new Date() }: { withinDays?: number; now?: Date } = {},
): string | null {
  const days = daysUntil(iso, now);
  if (days === null || days > withinDays) return null;
  if (days < 0) return "Closed";
  if (days === 0) return "Closes today";
  if (days === 1) return "Closes tomorrow";
  return `Closes in ${days} days`;
}

/** Human-readable long date for detail views. */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" });
}
