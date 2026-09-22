"use client";

import { Loader2 } from "lucide-react";
import { useEffect, useRef } from "react";

import { JobCard } from "@/components/jobs/JobCard";
import { Button } from "@/components/ui/button";
import type { JobSummary } from "@/types/api";

export interface JobListProps {
  jobs: JobSummary[];
  isLoading: boolean;
  error: string | null;
  hasNext: boolean;
  total: number;
  savedJobIds: Set<string>;
  pendingSaveIds: Set<string>;
  onToggleSave: (jobId: string) => void;
  onLoadMore: () => void;
  emptyMessage?: string;
}

/**
 * Card list with infinite scroll (an IntersectionObserver sentinel) and a
 * "Load more" button as the keyboard/no-JS-observer fallback.
 */
export function JobList({
  jobs,
  isLoading,
  error,
  hasNext,
  total,
  savedJobIds,
  pendingSaveIds,
  onToggleSave,
  onLoadMore,
  emptyMessage = "No jobs match your filters yet",
}: JobListProps) {
  const sentinelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const node = sentinelRef.current;
    if (!node || !hasNext || isLoading || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) onLoadMore();
      },
      { rootMargin: "400px 0px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [hasNext, isLoading, onLoadMore, jobs.length]);

  if (error) {
    return (
      <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-6 text-center text-red-800">
        <p className="font-medium">Could not load jobs</p>
        <p className="mt-1 text-sm">{error}</p>
      </div>
    );
  }

  if (!isLoading && jobs.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-slate-300 bg-white p-12 text-center">
        <p className="text-base font-medium text-slate-700">{emptyMessage}</p>
        <p className="mt-1 text-sm text-slate-500">Try clearing a filter or broadening your search.</p>
      </div>
    );
  }

  return (
    <div>
      <p className="mb-3 hidden text-sm text-slate-600 md:block" aria-live="polite">
        {total.toLocaleString()} {total === 1 ? "job" : "jobs"}
      </p>

      <ul className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {jobs.map((job) => (
          <li key={job.id}>
            <JobCard
              job={job}
              saved={savedJobIds.has(job.id)}
              savePending={pendingSaveIds.has(job.id)}
              onToggleSave={onToggleSave}
            />
          </li>
        ))}
        {isLoading && jobs.length === 0
          ? Array.from({ length: 6 }, (_, i) => (
              <li key={`skeleton-${i}`} className="h-36 animate-pulse rounded-xl border border-slate-200 bg-white" />
            ))
          : null}
      </ul>

      <div ref={sentinelRef} aria-hidden className="h-px" />

      <div className="mt-6 flex justify-center">
        {isLoading && jobs.length > 0 ? (
          <span className="inline-flex items-center gap-2 text-sm text-slate-500">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Loading more…
          </span>
        ) : hasNext ? (
          <Button variant="outline" onClick={onLoadMore}>
            Load more
          </Button>
        ) : jobs.length > 0 ? (
          <span className="text-sm text-slate-400">You&apos;ve reached the end</span>
        ) : null}
      </div>
    </div>
  );
}
