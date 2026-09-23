"use client";

import { Building2, ClipboardList, ExternalLink } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Badge, type BadgeVariant } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { useRefreshOnFocus } from "@/hooks/use-refresh-on-focus";
import { toast } from "@/hooks/use-toast";
import { ApiError } from "@/lib/api-client";
import { listApplications, updateApplicationStatus } from "@/lib/applications";
import { relativeTime } from "@/lib/time";
import type { Application, ApplicationStatus } from "@/types/api";

/** Tracker columns, in funnel order. Every status the API can return has a home here. */
const STATUS_ORDER: readonly ApplicationStatus[] = [
  "saved",
  "applied_pending_confirmation",
  "applied",
  "screening",
  "interview",
  "offer",
  "rejected",
  "withdrawn",
];

const STATUS_LABELS: Record<ApplicationStatus, string> = {
  saved: "Saved",
  applied_pending_confirmation: "Pending confirmation",
  applied: "Applied",
  screening: "Screening",
  interview: "Interview",
  offer: "Offer",
  rejected: "Rejected",
  withdrawn: "Withdrawn",
};

const STATUS_VARIANTS: Record<ApplicationStatus, BadgeVariant> = {
  saved: "neutral",
  applied_pending_confirmation: "yellow",
  applied: "blue",
  screening: "teal",
  interview: "teal",
  offer: "green",
  rejected: "red",
  withdrawn: "neutral",
};

const STATUS_OPTIONS = STATUS_ORDER.map((value) => ({ value, label: STATUS_LABELS[value] }));

/** Match score arrives as a Decimal string; render it as a whole percentage. */
function formatScore(score: Application["match_score"]): string | null {
  if (score === null) return null;
  const value = Number(score);
  return Number.isNaN(value) ? null : `${Math.round(value)}% match`;
}

export default function ApplicationsPage() {
  const router = useRouter();
  const { status: authStatus } = useSession();

  const [applications, setApplications] = useState<Application[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (authStatus === "unauthenticated") {
      router.replace(`/login?callbackUrl=${encodeURIComponent("/applications")}`);
    }
  }, [authStatus, router]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setApplications(await listApplications());
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not load your applications");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (authStatus === "authenticated") void load();
  }, [authStatus, load]);

  // Statuses change on other routes (marking a job applied) and in other tabs,
  // so a mount-only fetch goes stale. Re-pull whenever the page regains focus.
  useRefreshOnFocus(load, { enabled: authStatus === "authenticated" });

  const onChangeStatus = useCallback(
    (application: Application, next: ApplicationStatus) => {
      if (next === application.status || pending.has(application.id)) return;
      setPending((current) => new Set(current).add(application.id));

      void updateApplicationStatus(application.id, next)
        .then((updated) => {
          setApplications((current) =>
            current.map((item) => (item.id === updated.id ? updated : item)),
          );
          toast({
            title: `Moved to ${STATUS_LABELS[next]}`,
            description: `${application.job.title} at ${application.job.company_name}`,
            variant: "success",
          });
        })
        .catch((caught: unknown) => {
          toast({
            title: "Could not update the status",
            description: caught instanceof ApiError ? caught.message : "Please try again.",
            variant: "error",
          });
        })
        .finally(() => {
          setPending((current) => {
            const nextPending = new Set(current);
            nextPending.delete(application.id);
            return nextPending;
          });
        });
    },
    [pending],
  );

  // Group into funnel columns, keeping the API's most-recently-updated-first order.
  const grouped = useMemo(() => {
    const buckets = new Map<ApplicationStatus, Application[]>(
      STATUS_ORDER.map((key) => [key, [] as Application[]]),
    );
    for (const application of applications) {
      buckets.get(application.status)?.push(application);
    }
    return buckets;
  }, [applications]);

  if (authStatus === "loading" || (authStatus === "authenticated" && loading)) {
    return (
      <div className="space-y-3" aria-hidden>
        {Array.from({ length: 4 }, (_, i) => (
          <div key={i} className="h-24 animate-pulse rounded-xl border border-slate-200 bg-white" />
        ))}
      </div>
    );
  }
  if (authStatus !== "authenticated") return null;

  return (
    <div>
      <header className="mb-5 flex items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Application tracker</h1>
          <p className="mt-1 text-sm text-slate-600" aria-live="polite">
            {applications.length.toLocaleString()}{" "}
            {applications.length === 1 ? "application" : "applications"}
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
          <p className="font-medium">Could not load your applications</p>
          <p className="mt-1 text-sm">{error}</p>
          <Button variant="outline" size="sm" className="mt-4" onClick={() => void load()}>
            Try again
          </Button>
        </div>
      ) : applications.length === 0 ? (
        <div className="rounded-xl border border-dashed border-slate-300 bg-white p-12 text-center">
          <ClipboardList className="mx-auto h-8 w-8 text-slate-300" aria-hidden />
          <p className="mt-3 text-base font-medium text-slate-700">Nothing tracked yet</p>
          <p className="mt-1 text-sm text-slate-500">
            Use &ldquo;Apply Now&rdquo; on a job, then mark it as applied — it will show up here.
          </p>
          <Link href="/jobs">
            <Button className="mt-4">Browse jobs</Button>
          </Link>
        </div>
      ) : (
        <div className="space-y-8">
          {STATUS_ORDER.map((status) => {
            const items = grouped.get(status) ?? [];
            if (items.length === 0) return null;
            return (
              <section key={status} aria-labelledby={`status-${status}`}>
                <h2 id={`status-${status}`} className="mb-3 flex items-center gap-2 text-sm font-semibold">
                  <Badge variant={STATUS_VARIANTS[status]}>{STATUS_LABELS[status]}</Badge>
                  <span className="text-slate-500">{items.length}</span>
                </h2>
                <ul className="space-y-3">
                  {items.map((application) => (
                    <li key={application.id}>
                      <ApplicationRow
                        application={application}
                        busy={pending.has(application.id)}
                        onChangeStatus={onChangeStatus}
                      />
                    </li>
                  ))}
                </ul>
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}

interface ApplicationRowProps {
  application: Application;
  busy: boolean;
  onChangeStatus: (application: Application, next: ApplicationStatus) => void;
}

function ApplicationRow({ application, busy, onChangeStatus }: ApplicationRowProps) {
  const { job } = application;
  const score = formatScore(application.match_score);
  const lastEvent = application.events.at(-1);

  return (
    <article className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="flex items-center gap-1.5 text-sm font-medium text-slate-600">
            <Building2 className="h-4 w-4 shrink-0" aria-hidden />
            <span className="truncate">{job.company_name}</span>
          </p>
          <h3 className="mt-0.5 text-base font-semibold leading-snug">
            <Link
              href={`/jobs/${job.id}`}
              className="rounded hover:text-teal-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
            >
              {job.title}
            </Link>
          </h3>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            {job.location ? <Badge variant="outline">{job.location}</Badge> : null}
            {score ? <Badge variant="teal">{score}</Badge> : null}
          </div>
          <p className="mt-2 text-xs text-slate-500">
            {application.applied_at
              ? `Applied ${relativeTime(application.applied_at)}`
              : `Added ${relativeTime(application.created_at)}`}
            {lastEvent ? ` · last update ${relativeTime(lastEvent.event_time)}` : ""}
          </p>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <Select<ApplicationStatus>
            aria-label={`Status for ${job.title} at ${job.company_name}`}
            value={application.status}
            onChange={(next) => onChangeStatus(application, next)}
            options={STATUS_OPTIONS}
            className={busy ? "w-48 opacity-50" : "w-48"}
          />
          <a
            href={job.source_url}
            target="_blank"
            rel="noopener noreferrer"
            aria-label={`Open the posting for ${job.title} at ${job.company_name}`}
            className="inline-flex h-10 w-10 items-center justify-center rounded-md border border-slate-300 text-slate-600 hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
          >
            <ExternalLink className="h-4 w-4" aria-hidden />
          </a>
        </div>
      </div>
    </article>
  );
}
