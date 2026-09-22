/**
 * Application tracker calls. Users apply on the employer's site (ADR 002);
 * these only record what they tell us, and the backend writes an
 * `application_events` row for every status change.
 */

import { api } from "@/lib/api-client";
import type { Application, ApplicationStatus } from "@/types/api";

/**
 * Record that the user applied to `jobId`. Creates the application if it
 * does not exist yet, otherwise moves the existing one to `applied`.
 * Passing `resumeVersionId` stores the transparent match score alongside it.
 */
export async function markAsApplied(
  jobId: string,
  resumeVersionId?: string | null,
): Promise<Application> {
  return api.post<Application>("/applications", {
    job_id: jobId,
    resume_version_id: resumeVersionId ?? null,
    status: "applied",
  });
}

/** Move an application to a new status; optionally attach notes / a follow-up date. */
export async function updateApplicationStatus(
  applicationId: string,
  status: ApplicationStatus,
  extra: { notes?: string; follow_up_date?: string } = {},
): Promise<Application> {
  return api.patch<Application>(`/applications/${applicationId}/status`, { status, ...extra });
}

/** The current user's applications, most recently updated first. */
export async function listApplications(): Promise<Application[]> {
  return api.get<Application[]>("/applications");
}

/** Open the employer's posting in a new tab without leaking the referrer or window handle. */
export function openSourceUrl(url: string): void {
  window.open(url, "_blank", "noopener,noreferrer");
}
