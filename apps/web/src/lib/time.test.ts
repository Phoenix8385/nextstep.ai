import { describe, expect, it } from "vitest";

import { daysUntil, deadlineLabel, relativeTime } from "@/lib/time";

const NOW = new Date("2026-09-21T12:00:00Z");

describe("relativeTime", () => {
  it("formats recent timestamps", () => {
    expect(relativeTime("2026-09-21T11:59:40Z", NOW)).toBe("just now");
    expect(relativeTime("2026-09-21T11:55:00Z", NOW)).toBe("5 minutes ago");
    expect(relativeTime("2026-09-21T10:00:00Z", NOW)).toBe("2 hours ago");
    expect(relativeTime("2026-09-21T11:00:00Z", NOW)).toBe("1 hour ago");
    expect(relativeTime("2026-09-18T12:00:00Z", NOW)).toBe("3 days ago");
    expect(relativeTime("2026-09-01T12:00:00Z", NOW)).toBe("2 weeks ago");
  });

  it("handles missing or invalid input", () => {
    expect(relativeTime(null, NOW)).toBe("unknown");
    expect(relativeTime("not a date", NOW)).toBe("unknown");
  });
});

describe("deadlineLabel", () => {
  it("only labels deadlines inside the window", () => {
    expect(deadlineLabel("2026-09-24T12:00:00Z", { now: NOW })).toBe("Closes in 3 days");
    expect(deadlineLabel("2026-09-22T12:00:00Z", { now: NOW })).toBe("Closes tomorrow");
    expect(deadlineLabel("2026-09-21T18:00:00Z", { now: NOW })).toBe("Closes tomorrow"); // ceil(0.25d)
    expect(deadlineLabel("2026-09-21T12:00:00Z", { now: NOW })).toBe("Closes today");
    expect(deadlineLabel("2026-09-19T12:00:00Z", { now: NOW })).toBe("Closed");
    expect(deadlineLabel("2026-10-30T12:00:00Z", { now: NOW })).toBeNull();
    expect(deadlineLabel(null, { now: NOW })).toBeNull();
  });

  it("daysUntil is null without a deadline", () => {
    expect(daysUntil(null)).toBeNull();
    expect(daysUntil("2026-09-28T12:00:00Z", NOW)).toBe(7);
  });
});
