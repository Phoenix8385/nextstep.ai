/**
 * Job dashboard state: filters, the paged job list, and the user's saved-job ids.
 *
 * Saving is optimistic: the id is toggled locally first, the API call follows,
 * and the change is rolled back if the call fails.
 */

import { enableMapSet } from "immer";
import { create } from "zustand";
import { immer } from "zustand/middleware/immer";

import { api, ApiError } from "@/lib/api-client";
import type { ExperienceLevel, JobPage, JobSummary, SavedJob, WorkMode } from "@/types/api";

enableMapSet();

export interface JobFilters {
  role: string;
  company: string;
  location: string;
  work_mode: WorkMode | "";
  experience_level: ExperienceLevel | "";
}

export const EMPTY_FILTERS: JobFilters = {
  role: "",
  company: "",
  location: "",
  work_mode: "",
  experience_level: "",
};

export const PAGE_SIZE = 20;

export interface JobsState {
  jobs: JobSummary[];
  filters: JobFilters;
  page: number;
  total: number;
  hasNext: boolean;
  isLoading: boolean;
  error: string | null;
  savedJobIds: Set<string>;
  /** Ids whose save/unsave request is in flight (prevents double toggles). */
  pendingSaveIds: Set<string>;

  setFilters: (patch: Partial<JobFilters>) => void;
  clearFilters: () => void;
  /** Fetch page 1 with the current filters (replaces the list). */
  fetchJobs: () => Promise<void>;
  /** Fetch the next page and append it. No-op when there is none or a load is running. */
  fetchNextPage: () => Promise<void>;
  /** Load the user's saved ids (call once after sign-in). */
  loadSavedJobIds: () => Promise<void>;
  /** Optimistically save or unsave a job. Rejects with the API error on failure. */
  toggleSaved: (jobId: string) => Promise<void>;
}

/** Build the `/jobs` query object, omitting empty filters. */
export function filtersToQuery(
  filters: JobFilters,
  page: number,
): Record<string, string | number> {
  const query: Record<string, string | number> = { page, page_size: PAGE_SIZE };
  for (const [key, value] of Object.entries(filters)) {
    const trimmed = value.trim();
    if (trimmed) query[key] = trimmed;
  }
  return query;
}

export function hasActiveFilters(filters: JobFilters): boolean {
  return Object.values(filters).some((value) => value.trim() !== "");
}

let requestSerial = 0; // discard responses that arrive after a newer request started

export const useJobsStore = create<JobsState>()(
  immer((set, get) => ({
    jobs: [],
    filters: { ...EMPTY_FILTERS },
    page: 1,
    total: 0,
    hasNext: false,
    isLoading: false,
    error: null,
    savedJobIds: new Set<string>(),
    pendingSaveIds: new Set<string>(),

    setFilters: (patch) => {
      set((state) => {
        Object.assign(state.filters, patch);
      });
    },

    clearFilters: () => {
      set((state) => {
        state.filters = { ...EMPTY_FILTERS };
      });
    },

    fetchJobs: async () => {
      const serial = ++requestSerial;
      set((state) => {
        state.isLoading = true;
        state.error = null;
      });
      try {
        const page = await api.get<JobPage>("/jobs", {
          query: filtersToQuery(get().filters, 1),
          token: null,
        });
        if (serial !== requestSerial) return;
        set((state) => {
          state.jobs = page.items;
          state.page = page.page;
          state.total = page.total;
          state.hasNext = page.has_next;
          state.isLoading = false;
        });
      } catch (error) {
        if (serial !== requestSerial) return;
        set((state) => {
          state.isLoading = false;
          state.error = describe(error);
        });
      }
    },

    fetchNextPage: async () => {
      const { hasNext, isLoading, page, filters } = get();
      if (!hasNext || isLoading) return;
      const serial = ++requestSerial;
      set((state) => {
        state.isLoading = true;
      });
      try {
        const next = await api.get<JobPage>("/jobs", {
          query: filtersToQuery(filters, page + 1),
          token: null,
        });
        if (serial !== requestSerial) return;
        set((state) => {
          const seen = new Set(state.jobs.map((job) => job.id));
          state.jobs.push(...next.items.filter((job) => !seen.has(job.id)));
          state.page = next.page;
          state.total = next.total;
          state.hasNext = next.has_next;
          state.isLoading = false;
        });
      } catch (error) {
        if (serial !== requestSerial) return;
        set((state) => {
          state.isLoading = false;
          state.error = describe(error);
        });
      }
    },

    loadSavedJobIds: async () => {
      try {
        const saved = await api.get<SavedJob[]>("/saved-jobs");
        set((state) => {
          state.savedJobIds = new Set(saved.map((entry) => entry.job.id));
        });
      } catch (error) {
        // Not signed in (401) simply means nothing is saved yet.
        if (!(error instanceof ApiError && error.isUnauthorized)) throw error;
        set((state) => {
          state.savedJobIds = new Set();
        });
      }
    },

    toggleSaved: async (jobId) => {
      if (get().pendingSaveIds.has(jobId)) return;
      const wasSaved = get().savedJobIds.has(jobId);

      set((state) => {
        state.pendingSaveIds.add(jobId);
        if (wasSaved) state.savedJobIds.delete(jobId);
        else state.savedJobIds.add(jobId);
      });

      try {
        if (wasSaved) await api.delete(`/jobs/${jobId}/save`);
        else await api.post(`/jobs/${jobId}/save`);
      } catch (error) {
        set((state) => {
          if (wasSaved) state.savedJobIds.add(jobId);
          else state.savedJobIds.delete(jobId);
        });
        throw error;
      } finally {
        set((state) => {
          state.pendingSaveIds.delete(jobId);
        });
      }
    },
  })),
);

function describe(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Something went wrong";
}
