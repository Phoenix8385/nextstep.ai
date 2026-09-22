"use client";

import { ArrowLeft, Bookmark, Building2, CalendarClock, MapPin, Sparkles } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import { useEffect, useState } from "react";

import { ApplyButton } from "@/components/jobs/ApplyButton";
import { EXPERIENCE_LABELS, WORK_MODE_LABELS } from "@/components/jobs/JobCard";
import { ResumeAnalysisModal } from "@/components/jobs/ResumeAnalysisModal";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { toast } from "@/hooks/use-toast";
import { ApiError } from "@/lib/api-client";
import { deadlineLabel, formatDate, relativeTime } from "@/lib/time";
import { cn } from "@/lib/utils";
import { useJobsStore } from "@/store/jobs";
import type { JobDetail } from "@/types/api";

/** Client half of the job detail page: header with save toggle, actions, and the full posting. */
export function JobDetailView({ job }: { job: JobDetail }) {
  const router = useRouter();
  const { status } = useSession();
  const [analysisOpen, setAnalysisOpen] = useState(false);

  const saved = useJobsStore((s) => s.savedJobIds.has(job.id));
  const savePending = useJobsStore((s) => s.pendingSaveIds.has(job.id));
  const toggleSaved = useJobsStore((s) => s.toggleSaved);
  const loadSavedJobIds = useJobsStore((s) => s.loadSavedJobIds);

  useEffect(() => {
    if (status === "authenticated") void loadSavedJobIds();
  }, [status, loadSavedJobIds]);

  function onToggleSave() {
    if (status !== "authenticated") {
      router.push(`/login?callbackUrl=${encodeURIComponent(`/jobs/${job.id}`)}`);
      return;
    }
    toggleSaved(job.id).catch((caught: unknown) => {
      toast({
        title: "Could not update saved jobs",
        description: caught instanceof ApiError ? caught.message : "Please try again.",
        variant: "error",
      });
    });
  }

  function onAnalyze() {
    if (status !== "authenticated") {
      router.push(`/login?callbackUrl=${encodeURIComponent(`/jobs/${job.id}`)}`);
      return;
    }
    setAnalysisOpen(true);
  }

  const closing = deadlineLabel(job.deadline, { withinDays: 365 });

  return (
    <article className="mx-auto max-w-3xl">
      <Link href="/jobs" className="inline-flex items-center gap-1 text-sm text-slate-600 hover:text-slate-900">
        <ArrowLeft className="h-4 w-4" aria-hidden /> Back to jobs
      </Link>

      <header className="mt-4 rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="flex items-center gap-1.5 text-sm font-medium text-slate-600">
              <Building2 className="h-4 w-4" aria-hidden /> {job.company_name}
            </p>
            <h1 className="mt-1 text-2xl font-bold leading-tight text-slate-900">{job.title}</h1>
          </div>
          <button
            type="button"
            onClick={onToggleSave}
            aria-pressed={saved}
            aria-label={saved ? "Remove from saved jobs" : "Save job"}
            disabled={savePending}
            className={cn(
              "shrink-0 rounded-full p-2 transition focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500",
              saved ? "text-teal-600 hover:bg-teal-50" : "text-slate-400 hover:bg-slate-100 hover:text-slate-600",
            )}
          >
            <Bookmark className="h-6 w-6" fill={saved ? "currentColor" : "none"} aria-hidden />
          </button>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          {job.location ? (
            <Badge variant="outline">
              <MapPin className="mr-1 h-3 w-3" aria-hidden /> {job.location}
            </Badge>
          ) : null}
          {job.work_mode ? <Badge variant="blue">{WORK_MODE_LABELS[job.work_mode]}</Badge> : null}
          {job.experience_level ? <Badge variant="neutral">{EXPERIENCE_LABELS[job.experience_level]}</Badge> : null}
          {job.is_new ? <Badge variant="teal">Just Posted</Badge> : null}
          {!job.is_active ? <Badge variant="red">No longer listed</Badge> : null}
        </div>

        <dl className="mt-4 grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
          <div className="flex items-center gap-2">
            <dt className="text-slate-500">Posted</dt>
            <dd className="font-medium" title={formatDate(job.posted_at)}>
              {relativeTime(job.posted_at ?? job.detected_at)}
            </dd>
          </div>
          <div className="flex items-center gap-2">
            <dt className="flex items-center gap-1 text-slate-500">
              <CalendarClock className="h-4 w-4" aria-hidden /> Deadline
            </dt>
            <dd className="font-medium">
              {job.deadline ? `${formatDate(job.deadline)}${closing ? ` · ${closing}` : ""}` : "Not stated"}
            </dd>
          </div>
        </dl>

        <div className="mt-6 flex flex-col gap-3 sm:flex-row">
          <Button variant="outline" size="lg" className="flex-1" onClick={onAnalyze}>
            <Sparkles className="h-4 w-4" aria-hidden /> Analyze My Resume
          </Button>
          <ApplyButton job={job} size="lg" className="flex-1" />
        </div>
      </header>

      {job.required_skills.length ? (
        <section className="mt-6" aria-labelledby="skills-heading">
          <h2 id="skills-heading" className="text-sm font-semibold uppercase tracking-wide text-slate-500">
            Skills mentioned
          </h2>
          <ul className="mt-2 flex flex-wrap gap-2">
            {job.required_skills.map((skill) => (
              <li key={skill}>
                <Badge variant="neutral">{skill}</Badge>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {job.eligibility ? (
        <section className="mt-6 rounded-xl border border-amber-200 bg-amber-50 p-4" aria-labelledby="elig-heading">
          <h2 id="elig-heading" className="text-sm font-semibold text-amber-900">
            Eligibility
          </h2>
          <p className="mt-1 whitespace-pre-line text-sm text-amber-900">{job.eligibility}</p>
        </section>
      ) : null}

      {job.requirements ? (
        <section className="mt-6" aria-labelledby="req-heading">
          <h2 id="req-heading" className="text-sm font-semibold uppercase tracking-wide text-slate-500">
            Requirements
          </h2>
          <p className="mt-2 whitespace-pre-line text-sm leading-relaxed text-slate-800">{job.requirements}</p>
        </section>
      ) : null}

      <section className="mt-6" aria-labelledby="desc-heading">
        <h2 id="desc-heading" className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          Description
        </h2>
        <p className="mt-2 whitespace-pre-line text-sm leading-relaxed text-slate-800">
          {job.description ?? "No description provided."}
        </p>
      </section>

      <p className="mt-8 text-xs text-slate-400">
        Source: {job.source_name} · Listing id {job.external_job_id}
      </p>

      <ResumeAnalysisModal job={job} open={analysisOpen} onOpenChange={setAnalysisOpen} />
    </article>
  );
}
