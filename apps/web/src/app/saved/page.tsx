"use client";

import { Bookmark } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import { useCallback, useEffect, useState } from "react";

import { JobCard } from "@/components/jobs/JobCard";
import { Button } from "@/components/ui/button";
import { toast } from "@/hooks/use-toast";
import { api, ApiError } from "@/lib/api-client";
import { useJobsStore } from "@/store/jobs";
import type { SavedJob } from "@/types/api";

/** Bookmarked jobs, newest save first. Unsaving removes the card immediately. */
export default function SavedJobsPage() {
  const router = useRouter();
  const { status } = useSession();

  const [saved, setSaved] = useState<SavedJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<Set<string>>(new Set());

  // Keep the dashboard's bookmark icons in sync with what happens here.
  const loadSavedJobIds = useJobsStore((s) => s.loadSavedJobIds);

  useEffect(() => {
    if (status === "unauthenticated") {
      router.replace(`/login?callbackUrl=${encodeURIComponent("/saved")}`);
    }
  }, [status, router]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setSaved(await api.get<SavedJob[]>("/saved-jobs"));
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not load your saved jobs");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (status === "authenticated") void load();
  }, [status, load]);

  const onToggleSave = useCallback(
    (jobId: string) => {
      if (pending.has(jobId)) return;
      setPending((current) => new Set(current).add(jobId));
      const previous = saved;
      // Optimistic: drop the card, restore it if the request fails.
      setSaved((current) => current.filter((entry) => entry.job.id !== jobId));

      void api
        .delete(`/jobs/${jobId}/save`)
        .then(() => loadSavedJobIds())
        .catch((caught: unknown) => {
          setSaved(previous);
          toast({
            title: "Could not remove the bookmark",
            description: caught instanceof ApiError ? caught.message : "Please try again.",
            variant: "error",
          });
        })
        .finally(() => {
          setPending((current) => {
            const next = new Set(current);
            next.delete(jobId);
            return next;
          });
        });
    },
    [pending, saved, loadSavedJobIds],
  );

  if (status === "loading" || (status === "authenticated" && loading)) {
    return (
      <ul className="grid grid-cols-1 gap-3 md:grid-cols-2" aria-hidden>
        {Array.from({ length: 4 }, (_, i) => (
          <li
            key={i}
            className="h-36 animate-pulse rounded-xl border border-slate-200 bg-white"
          />
        ))}
      </ul>
    );
  }
  if (status !== "authenticated") return null;

  return (
    <div>
      <header className="mb-4 flex items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Saved jobs</h1>
          <p className="mt-1 text-sm text-slate-600" aria-live="polite">
            {saved.length.toLocaleString()} {saved.length === 1 ? "job" : "jobs"} bookmarked
          </p>
        </div>
        <Link href="/jobs">
          <Button variant="outline" size="sm">
            Browse jobs
          </Button>
        </Link>
      </header>

      {error ? (
        <div
          role="alert"
          className="rounded-xl border border-red-200 bg-red-50 p-6 text-center text-red-800"
        >
          <p className="font-medium">Could not load your saved jobs</p>
          <p className="mt-1 text-sm">{error}</p>
          <Button variant="outline" size="sm" className="mt-4" onClick={() => void load()}>
            Try again
          </Button>
        </div>
      ) : saved.length === 0 ? (
        <div className="rounded-xl border border-dashed border-slate-300 bg-white p-12 text-center">
          <Bookmark className="mx-auto h-8 w-8 text-slate-300" aria-hidden />
          <p className="mt-3 text-base font-medium text-slate-700">No saved jobs yet</p>
          <p className="mt-1 text-sm text-slate-500">
            Tap the bookmark on any job card to keep it here.
          </p>
          <Link href="/jobs">
            <Button className="mt-4">Browse jobs</Button>
          </Link>
        </div>
      ) : (
        <ul className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {saved.map((entry) => (
            <li key={entry.id}>
              <JobCard
                job={entry.job}
                saved
                savePending={pending.has(entry.job.id)}
                onToggleSave={onToggleSave}
              />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
