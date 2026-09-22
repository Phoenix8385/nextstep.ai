import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { JobDetailView } from "@/components/jobs/JobDetailView";
import { ApiError, apiFetch } from "@/lib/api-client";
import type { JobDetail } from "@/types/api";

interface PageProps {
  params: { id: string };
}

async function loadJob(id: string): Promise<JobDetail | null> {
  try {
    // Job detail is public, so the server can fetch it without a token.
    return await apiFetch<JobDetail>(`/jobs/${id}`, { token: null, cache: "no-store" });
  } catch (error) {
    if (error instanceof ApiError && (error.status === 404 || error.status === 422)) return null;
    throw error;
  }
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const job = await loadJob(params.id);
  return { title: job ? `${job.title} at ${job.company_name} · NextStep.ai` : "Job not found" };
}

export default async function JobPage({ params }: PageProps) {
  const job = await loadJob(params.id);
  if (!job) notFound();
  return <JobDetailView job={job} />;
}
