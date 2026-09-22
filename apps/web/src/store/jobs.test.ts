import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    api: { get: vi.fn(), post: vi.fn(), delete: vi.fn(), put: vi.fn(), patch: vi.fn() },
  };
});

import { api, ApiError } from "@/lib/api-client";
import { EMPTY_FILTERS, filtersToQuery, hasActiveFilters, useJobsStore } from "@/store/jobs";
import type { JobPage, JobSummary } from "@/types/api";

function job(id: string, title = "Job " + id): JobSummary {
  return {
    id,
    company_name: "Acme",
    title,
    location: "Remote",
    work_mode: "remote",
    experience_level: "entry_level",
    required_skills: ["Python"],
    source_url: "https://example.com",
    posted_at: null,
    detected_at: "2026-09-21T00:00:00Z",
    deadline: null,
    is_active: true,
    is_new: false,
  };
}

function page(items: JobSummary[], extra: Partial<JobPage> = {}): JobPage {
  return {
    items,
    page: 1,
    page_size: 20,
    total: items.length,
    total_pages: 1,
    has_next: false,
    ...extra,
  };
}

beforeEach(() => {
  vi.mocked(api.get).mockReset();
  vi.mocked(api.post).mockReset();
  vi.mocked(api.delete).mockReset();
  useJobsStore.setState({
    jobs: [],
    filters: { ...EMPTY_FILTERS },
    page: 1,
    total: 0,
    hasNext: false,
    isLoading: false,
    error: null,
    savedJobIds: new Set(),
    pendingSaveIds: new Set(),
  });
});

describe("filters", () => {
  it("builds a query with only the non-empty filters", () => {
    expect(filtersToQuery({ ...EMPTY_FILTERS, role: " intern ", work_mode: "remote" }, 3)).toEqual({
      page: 3,
      page_size: 20,
      role: "intern",
      work_mode: "remote",
    });
    expect(hasActiveFilters(EMPTY_FILTERS)).toBe(false);
    expect(hasActiveFilters({ ...EMPTY_FILTERS, company: "figma" })).toBe(true);
  });

  it("setFilters merges and clearFilters resets", () => {
    useJobsStore.getState().setFilters({ company: "figma" });
    useJobsStore.getState().setFilters({ location: "NYC" });
    expect(useJobsStore.getState().filters).toMatchObject({ company: "figma", location: "NYC" });
    useJobsStore.getState().clearFilters();
    expect(useJobsStore.getState().filters).toEqual(EMPTY_FILTERS);
  });
});

describe("fetchJobs / fetchNextPage", () => {
  it("loads page 1 with filters and appends page 2 without duplicates", async () => {
    useJobsStore.getState().setFilters({ role: "engineer" });
    vi.mocked(api.get).mockResolvedValueOnce(page([job("1"), job("2")], { has_next: true, total: 3 }));

    await useJobsStore.getState().fetchJobs();

    expect(api.get).toHaveBeenCalledWith("/jobs", {
      query: { page: 1, page_size: 20, role: "engineer" },
      token: null,
    });
    expect(useJobsStore.getState().jobs.map((j) => j.id)).toEqual(["1", "2"]);
    expect(useJobsStore.getState().hasNext).toBe(true);

    vi.mocked(api.get).mockResolvedValueOnce(page([job("2"), job("3")], { page: 2, total: 3 }));
    await useJobsStore.getState().fetchNextPage();

    expect(api.get).toHaveBeenLastCalledWith("/jobs", {
      query: { page: 2, page_size: 20, role: "engineer" },
      token: null,
    });
    expect(useJobsStore.getState().jobs.map((j) => j.id)).toEqual(["1", "2", "3"]);
    expect(useJobsStore.getState().hasNext).toBe(false);
    expect(useJobsStore.getState().isLoading).toBe(false);
  });

  it("records an error message on failure", async () => {
    vi.mocked(api.get).mockRejectedValueOnce(new ApiError(500, "boom"));
    await useJobsStore.getState().fetchJobs();
    expect(useJobsStore.getState().error).toBe("boom");
    expect(useJobsStore.getState().isLoading).toBe(false);
  });

  it("does not fetch the next page when there is none", async () => {
    await useJobsStore.getState().fetchNextPage();
    expect(api.get).not.toHaveBeenCalled();
  });
});

describe("toggleSaved", () => {
  it("saves optimistically and calls POST", async () => {
    vi.mocked(api.post).mockResolvedValueOnce({});
    const promise = useJobsStore.getState().toggleSaved("j1");
    expect(useJobsStore.getState().savedJobIds.has("j1")).toBe(true); // before the request resolves
    expect(useJobsStore.getState().pendingSaveIds.has("j1")).toBe(true);
    await promise;
    expect(api.post).toHaveBeenCalledWith("/jobs/j1/save");
    expect(useJobsStore.getState().pendingSaveIds.has("j1")).toBe(false);
  });

  it("unsaves with DELETE and rolls back on failure", async () => {
    useJobsStore.setState({ savedJobIds: new Set(["j1"]) });
    vi.mocked(api.delete).mockRejectedValueOnce(new ApiError(500, "nope"));

    await expect(useJobsStore.getState().toggleSaved("j1")).rejects.toBeInstanceOf(ApiError);

    expect(api.delete).toHaveBeenCalledWith("/jobs/j1/save");
    expect(useJobsStore.getState().savedJobIds.has("j1")).toBe(true); // rolled back
    expect(useJobsStore.getState().pendingSaveIds.size).toBe(0);
  });

  it("ignores a second toggle while one is in flight", async () => {
    let resolve: () => void = () => undefined;
    vi.mocked(api.post).mockReturnValueOnce(
      new Promise<void>((r) => {
        resolve = r;
      }),
    );
    const first = useJobsStore.getState().toggleSaved("j1");
    await useJobsStore.getState().toggleSaved("j1"); // no-op while pending
    expect(api.post).toHaveBeenCalledTimes(1);
    resolve();
    await first;
  });

  it("loadSavedJobIds treats 401 as empty", async () => {
    vi.mocked(api.get).mockRejectedValueOnce(new ApiError(401, "Not authenticated"));
    await useJobsStore.getState().loadSavedJobIds();
    expect(useJobsStore.getState().savedJobIds.size).toBe(0);

    vi.mocked(api.get).mockResolvedValueOnce([{ id: "s", saved_at: "", job: job("j9") }]);
    await useJobsStore.getState().loadSavedJobIds();
    expect(useJobsStore.getState().savedJobIds.has("j9")).toBe(true);
  });
});
