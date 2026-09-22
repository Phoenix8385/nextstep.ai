"use client";

import { Bookmark, Building2, MapPin } from "lucide-react";
import Link from "next/link";
import type { MouseEvent } from "react";

import { Badge } from "@/components/ui/badge";
import { deadlineLabel, relativeTime } from "@/lib/time";
import { cn } from "@/lib/utils";
import type { JobSummary } from "@/types/api";

export const WORK_MODE_LABELS: Record<NonNullable<JobSummary["work_mode"]>, string> = {
  remote: "Remote",
  hybrid: "Hybrid",
  onsite: "On-site",
};

export const EXPERIENCE_LABELS: Record<NonNullable<JobSummary["experience_level"]>, string> = {
  intern: "Internship",
  entry_level: "Entry-level",
  experienced: "Experienced",
};

export interface JobCardProps {
  job: JobSummary;
  saved: boolean;
  savePending?: boolean;
  onToggleSave: (jobId: string) => void;
}

/** One posting in the list. The whole card links to the detail page; the bookmark is a separate control. */
export function JobCard({ job, saved, savePending = false, onToggleSave }: JobCardProps) {
  const closing = deadlineLabel(job.deadline);

  function onBookmark(event: MouseEvent<HTMLButtonElement>) {
    event.preventDefault();
    event.stopPropagation();
    if (!savePending) onToggleSave(job.id);
  }

  return (
    <article className="relative rounded-xl border border-slate-200 bg-white p-4 shadow-sm transition hover:border-teal-300 hover:shadow-md">
      <Link
        href={`/jobs/${job.id}`}
        className="block focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 rounded-lg"
        aria-label={`${job.title} at ${job.company_name}`}
      >
        <div className="flex items-start justify-between gap-3 pr-10">
          <div className="min-w-0">
            <p className="flex items-center gap-1.5 text-sm font-medium text-slate-600">
              <Building2 className="h-4 w-4 shrink-0" aria-hidden />
              <span className="truncate">{job.company_name}</span>
            </p>
            <h3 className="mt-0.5 text-base font-semibold leading-snug text-slate-900">{job.title}</h3>
          </div>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          {job.location ? (
            <Badge variant="outline" className="max-w-full">
              <MapPin className="mr-1 h-3 w-3 shrink-0" aria-hidden />
              <span className="truncate">{job.location}</span>
            </Badge>
          ) : null}
          {job.work_mode ? <Badge variant="blue">{WORK_MODE_LABELS[job.work_mode]}</Badge> : null}
          {job.experience_level ? (
            <Badge variant="neutral">{EXPERIENCE_LABELS[job.experience_level]}</Badge>
          ) : null}
          {job.is_new ? <Badge variant="teal">Just Posted</Badge> : null}
          {closing ? <Badge variant={closing === "Closed" ? "red" : "yellow"}>{closing}</Badge> : null}
        </div>

        <p className="mt-3 text-xs text-slate-500">
          Posted {relativeTime(job.posted_at ?? job.detected_at)}
          {job.required_skills.length ? (
            <>
              {" · "}
              <span className="text-slate-600">{job.required_skills.slice(0, 4).join(", ")}</span>
              {job.required_skills.length > 4 ? ` +${job.required_skills.length - 4}` : ""}
            </>
          ) : null}
        </p>
      </Link>

      <button
        type="button"
        onClick={onBookmark}
        aria-pressed={saved}
        aria-label={saved ? "Remove from saved jobs" : "Save job"}
        disabled={savePending}
        className={cn(
          "absolute right-3 top-3 rounded-full p-2 transition focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500",
          saved ? "text-teal-600 hover:bg-teal-50" : "text-slate-400 hover:bg-slate-100 hover:text-slate-600",
          savePending && "opacity-50",
        )}
      >
        <Bookmark className="h-5 w-5" fill={saved ? "currentColor" : "none"} aria-hidden />
      </button>
    </article>
  );
}
