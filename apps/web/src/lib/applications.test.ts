import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() } };
});

import { api } from "@/lib/api-client";
import {
  listApplications,
  markAsApplied,
  openSourceUrl,
  updateApplicationStatus,
} from "@/lib/applications";

beforeEach(() => {
  vi.mocked(api.post).mockReset().mockResolvedValue({});
  vi.mocked(api.patch).mockReset().mockResolvedValue({});
  vi.mocked(api.get).mockReset().mockResolvedValue([]);
});

describe("markAsApplied", () => {
  it("posts status=applied for the job", async () => {
    await markAsApplied("job-1");
    expect(api.post).toHaveBeenCalledWith("/applications", {
      job_id: "job-1",
      resume_version_id: null,
      status: "applied",
    });
  });

  it("attaches the resume version when one is given", async () => {
    await markAsApplied("job-1", "version-7");
    expect(api.post).toHaveBeenCalledWith("/applications", {
      job_id: "job-1",
      resume_version_id: "version-7",
      status: "applied",
    });
  });

  it("normalises an undefined or null version to null", async () => {
    await markAsApplied("job-1", undefined);
    await markAsApplied("job-1", null);
    for (const call of vi.mocked(api.post).mock.calls) {
      expect((call[1] as { resume_version_id: unknown }).resume_version_id).toBeNull();
    }
  });
});

describe("updateApplicationStatus", () => {
  it("patches the status endpoint", async () => {
    await updateApplicationStatus("app-1", "interview");
    expect(api.patch).toHaveBeenCalledWith("/applications/app-1/status", { status: "interview" });
  });

  it("passes notes and follow-up date through", async () => {
    await updateApplicationStatus("app-1", "screening", {
      notes: "Recruiter call booked",
      follow_up_date: "2026-10-01",
    });
    expect(api.patch).toHaveBeenCalledWith("/applications/app-1/status", {
      status: "screening",
      notes: "Recruiter call booked",
      follow_up_date: "2026-10-01",
    });
  });
});

describe("listApplications", () => {
  it("gets the collection", async () => {
    await listApplications();
    expect(api.get).toHaveBeenCalledWith("/applications");
  });
});

describe("openSourceUrl", () => {
  it("opens in a new tab without leaking the opener or referrer", () => {
    const open = vi.fn();
    vi.stubGlobal("open", open);
    openSourceUrl("https://boards.greenhouse.io/acme/jobs/1");
    expect(open).toHaveBeenCalledWith(
      "https://boards.greenhouse.io/acme/jobs/1",
      "_blank",
      "noopener,noreferrer",
    );
    vi.unstubAllGlobals();
  });
});
