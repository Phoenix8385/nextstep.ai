"use client";

import { useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import { useCallback, useEffect, useRef } from "react";

import { FilterBar } from "@/components/jobs/FilterBar";
import { JobList } from "@/components/jobs/JobList";
import { toast } from "@/hooks/use-toast";
import { ApiError } from "@/lib/api-client";
import { useJobsStore, type JobFilters } from "@/store/jobs";

const FILTER_DEBOUNCE_MS = 300;

/** Job dashboard: sticky filter bar over a paged card list. */
export default function JobsPage() {
  const router = useRouter();
  const { status } = useSession();

  const jobs = useJobsStore((s) => s.jobs);
  const filters = useJobsStore((s) => s.filters);
  const total = useJobsStore((s) => s.total);
  const hasNext = useJobsStore((s) => s.hasNext);
  const isLoading = useJobsStore((s) => s.isLoading);
  const error = useJobsStore((s) => s.error);
  const savedJobIds = useJobsStore((s) => s.savedJobIds);
  const pendingSaveIds = useJobsStore((s) => s.pendingSaveIds);
  const setFilters = useJobsStore((s) => s.setFilters);
  const clearFilters = useJobsStore((s) => s.clearFilters);
  const fetchJobs = useJobsStore((s) => s.fetchJobs);
  const fetchNextPage = useJobsStore((s) => s.fetchNextPage);
  const loadSavedJobIds = useJobsStore((s) => s.loadSavedJobIds);
  const toggleSaved = useJobsStore((s) => s.toggleSaved);

  // Debounce text filters; selects change rarely so the same timer is fine for them.
  const timer = useRef<number | null>(null);
  useEffect(() => {
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => void fetchJobs(), FILTER_DEBOUNCE_MS);
    return () => {
      if (timer.current) window.clearTimeout(timer.current);
    };
  }, [filters, fetchJobs]);

  useEffect(() => {
    if (status === "authenticated") void loadSavedJobIds();
  }, [status, loadSavedJobIds]);

  const onToggleSave = useCallback(
    (jobId: string) => {
      if (status !== "authenticated") {
        router.push(`/login?callbackUrl=${encodeURIComponent("/jobs")}`);
        return;
      }
      toggleSaved(jobId).catch((caught: unknown) => {
        toast({
          title: "Could not update saved jobs",
          description: caught instanceof ApiError ? caught.message : "Please try again.",
          variant: "error",
        });
      });
    },
    [status, router, toggleSaved],
  );

  const onChange = useCallback((patch: Partial<JobFilters>) => setFilters(patch), [setFilters]);
  const onLoadMore = useCallback(() => void fetchNextPage(), [fetchNextPage]);

  return (
    <div>
      <FilterBar filters={filters} onChange={onChange} onClear={clearFilters} resultCount={total} />
      <div className="mt-4">
        <JobList
          jobs={jobs}
          isLoading={isLoading}
          error={error}
          hasNext={hasNext}
          total={total}
          savedJobIds={savedJobIds}
          pendingSaveIds={pendingSaveIds}
          onToggleSave={onToggleSave}
          onLoadMore={onLoadMore}
        />
      </div>
    </div>
  );
}
