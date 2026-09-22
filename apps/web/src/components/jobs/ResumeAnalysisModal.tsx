"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { FileText, Loader2, UploadCloud, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type DragEvent } from "react";

import { ApplyButton } from "@/components/jobs/ApplyButton";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api, ApiError } from "@/lib/api-client";
import { cn } from "@/lib/utils";
import type { AnalyzeResponse, EligibilityStatus, JobDetail, Resume, ResumeVersion } from "@/types/api";

const ACCEPTED_TYPES = [
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
];
const MAX_BYTES = 5 * 1024 * 1024;

type Step =
  | { kind: "loading-resumes" }
  | { kind: "choose"; resume: Resume | null; uploadNew: boolean }
  | { kind: "uploading"; label: string }
  | { kind: "analyzing" }
  | { kind: "result"; result: AnalyzeResponse; resumeVersionId: string }
  | { kind: "error"; message: string; retry: () => void };

export interface ResumeAnalysisModalProps {
  job: JobDetail;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * Step 1: pick the resume on file or upload a new one (upload → parse).
 * Step 2: POST /jobs/{id}/analyze and render the transparent match result.
 * Radix Dialog provides the focus trap and Escape-to-close.
 */
export function ResumeAnalysisModal({ job, open, onOpenChange }: ResumeAnalysisModalProps) {
  const [step, setStep] = useState<Step>({ kind: "loading-resumes" });

  const loadResumes = useCallback(async () => {
    setStep({ kind: "loading-resumes" });
    try {
      const resumes = await api.get<Resume[]>("/resumes");
      const withVersion = resumes.find((r) => r.latest_version) ?? null;
      setStep({ kind: "choose", resume: withVersion, uploadNew: withVersion === null });
    } catch (error) {
      setStep({ kind: "error", message: describe(error), retry: () => void loadResumes() });
    }
  }, []);

  useEffect(() => {
    if (open) void loadResumes();
  }, [open, loadResumes]);

  const analyze = useCallback(
    async (resumeVersionId: string) => {
      setStep({ kind: "analyzing" });
      try {
        const result = await api.post<AnalyzeResponse>(`/jobs/${job.id}/analyze`, {
          resume_version_id: resumeVersionId,
        });
        setStep({ kind: "result", result, resumeVersionId });
      } catch (error) {
        setStep({ kind: "error", message: describe(error), retry: () => void analyze(resumeVersionId) });
      }
    },
    [job.id],
  );

  const upload = useCallback(
    async (file: File) => {
      if (!ACCEPTED_TYPES.includes(file.type) && !/\.(pdf|docx)$/i.test(file.name)) {
        setStep({ kind: "error", message: "Please choose a PDF or DOCX file.", retry: () => void loadResumes() });
        return;
      }
      if (file.size > MAX_BYTES) {
        setStep({ kind: "error", message: "That file is larger than 5 MB.", retry: () => void loadResumes() });
        return;
      }
      try {
        setStep({ kind: "uploading", label: "Uploading…" });
        const form = new FormData();
        form.append("file", file);
        const resume = await api.post<Resume>("/resumes", form);
        setStep({ kind: "uploading", label: "Reading your resume…" });
        const version = await api.post<ResumeVersion>(`/resumes/${resume.id}/parse`);
        await analyze(version.id);
      } catch (error) {
        setStep({ kind: "error", message: describe(error), retry: () => void loadResumes() });
      }
    },
    [analyze, loadResumes],
  );

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/50" />
        <Dialog.Content
          className="fixed left-1/2 top-1/2 z-50 max-h-[90vh] w-[min(40rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-2xl bg-white p-6 shadow-2xl focus:outline-none"
          aria-describedby="analysis-desc"
        >
          <div className="flex items-start justify-between gap-4">
            <div>
              <Dialog.Title className="text-lg font-bold">Resume analysis</Dialog.Title>
              <Dialog.Description id="analysis-desc" className="mt-1 text-sm text-slate-600">
                {job.title} at {job.company_name}. Scores are a transparent skill overlap — nothing is invented.
              </Dialog.Description>
            </div>
            <Dialog.Close asChild>
              <Button variant="ghost" size="icon" aria-label="Close">
                <X className="h-5 w-5" aria-hidden />
              </Button>
            </Dialog.Close>
          </div>

          <div className="mt-6">
            {step.kind === "loading-resumes" ? (
              <Spinner label="Checking for a resume on file…" />
            ) : step.kind === "choose" ? (
              <ChooseStep
                step={step}
                onUseExisting={() => step.resume?.latest_version && void analyze(step.resume.latest_version.id)}
                onToggleUpload={(uploadNew) => setStep({ ...step, uploadNew })}
                onFile={(file) => void upload(file)}
              />
            ) : step.kind === "uploading" ? (
              <Spinner label={step.label} />
            ) : step.kind === "analyzing" ? (
              <Spinner label="Comparing your resume with this posting…" />
            ) : step.kind === "result" ? (
              <ResultStep job={job} result={step.result} resumeVersionId={step.resumeVersionId} />
            ) : (
              <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">
                <p className="font-medium">Something went wrong</p>
                <p className="mt-1">{step.message}</p>
                <Button variant="outline" size="sm" className="mt-3" onClick={step.retry}>
                  Try again
                </Button>
              </div>
            )}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

// --------------------------------------------------------------------------- //
// Step 1
// --------------------------------------------------------------------------- //

function ChooseStep({
  step,
  onUseExisting,
  onToggleUpload,
  onFile,
}: {
  step: Extract<Step, { kind: "choose" }>;
  onUseExisting: () => void;
  onToggleUpload: (uploadNew: boolean) => void;
  onFile: (file: File) => void;
}) {
  const { resume, uploadNew } = step;
  return (
    <div className="space-y-4">
      {resume ? (
        <div className="rounded-lg border border-slate-200 p-4">
          <p className="flex items-center gap-2 text-sm font-medium">
            <FileText className="h-4 w-4 text-teal-600" aria-hidden />
            {resume.file_name}
            <span className="text-xs font-normal text-slate-500">
              · {resume.latest_version?.parsed_skills.length ?? 0} skills detected
            </span>
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button onClick={onUseExisting}>Use my resume on file</Button>
            <Button variant="ghost" onClick={() => onToggleUpload(!uploadNew)}>
              {uploadNew ? "Cancel new upload" : "Upload a new version"}
            </Button>
          </div>
        </div>
      ) : (
        <p className="text-sm text-slate-700">Upload your resume to see how it lines up with this posting.</p>
      )}
      {uploadNew ? <Dropzone onFile={onFile} /> : null}
    </div>
  );
}

function Dropzone({ onFile }: { onFile: (file: File) => void }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    const file = event.dataTransfer.files[0];
    if (file) onFile(file);
  }

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => inputRef.current?.click()}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && inputRef.current?.click()}
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
      className={cn(
        "flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed p-8 text-center transition focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500",
        dragging ? "border-teal-500 bg-teal-50" : "border-slate-300 hover:border-teal-400 hover:bg-slate-50",
      )}
    >
      <UploadCloud className="h-8 w-8 text-teal-600" aria-hidden />
      <p className="mt-2 text-sm font-medium">Drop your resume here, or click to choose</p>
      <p className="mt-1 text-xs text-slate-500">PDF or DOCX, up to 5 MB</p>
      <input
        ref={inputRef}
        type="file"
        accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        className="sr-only"
        aria-label="Choose resume file"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) onFile(file);
          e.target.value = "";
        }}
      />
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Step 2
// --------------------------------------------------------------------------- //

const ELIGIBILITY: Record<EligibilityStatus, { label: string; variant: "green" | "yellow" | "red" }> = {
  likely_eligible: { label: "Likely Eligible", variant: "green" },
  uncertain: { label: "Uncertain", variant: "yellow" },
  not_eligible: { label: "Not Eligible", variant: "red" },
};

export function scoreColor(score: number): { ring: string; text: string } {
  if (score >= 70) return { ring: "stroke-green-500", text: "text-green-700" };
  if (score >= 40) return { ring: "stroke-amber-500", text: "text-amber-700" };
  return { ring: "stroke-red-500", text: "text-red-700" };
}

function ScoreRing({ score }: { score: number }) {
  const radius = 44;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - Math.min(100, Math.max(0, score)) / 100);
  const color = scoreColor(score);
  return (
    <div className="relative h-28 w-28" role="img" aria-label={`Match score ${score} percent`}>
      <svg viewBox="0 0 100 100" className="h-full w-full -rotate-90">
        <circle cx="50" cy="50" r={radius} className="fill-none stroke-slate-200" strokeWidth="8" />
        <circle
          cx="50"
          cy="50"
          r={radius}
          className={cn("fill-none transition-[stroke-dashoffset] duration-700", color.ring)}
          strokeWidth="8"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
        />
      </svg>
      <span className={cn("absolute inset-0 flex items-center justify-center text-2xl font-bold", color.text)}>
        {score}%
      </span>
    </div>
  );
}

function ResultStep({
  job,
  result,
  resumeVersionId,
}: {
  job: JobDetail;
  result: AnalyzeResponse;
  resumeVersionId: string;
}) {
  const eligibility = ELIGIBILITY[result.eligibility_status];
  return (
    <div className="space-y-6">
      <div className="flex flex-col items-center gap-4 sm:flex-row sm:items-start">
        <ScoreRing score={result.match_score} />
        <div className="flex-1 text-center sm:text-left">
          <p className="text-sm text-slate-600">
            {result.matching_skills.length} of {result.matching_skills.length + result.missing_skills.length} skills
            the posting mentions appear on your resume.
          </p>
          <div className="mt-3">
            <Badge variant={eligibility.variant}>{eligibility.label}</Badge>
            {!result.profile_on_file ? (
              <p className="mt-2 text-xs text-slate-500">Add graduation year and experience level to your profile for an eligibility check.</p>
            ) : null}
          </div>
          <ul className="mt-2 space-y-1 text-sm text-slate-700">
            {result.eligibility_reasons.map((reason) => (
              <li key={reason}>• {reason}</li>
            ))}
          </ul>
        </div>
      </div>

      <SkillGroup title="Matching skills" skills={result.matching_skills} variant="green" empty="None of the listed skills were found on your resume." />
      <SkillGroup title="Not found on your resume" skills={result.missing_skills} variant="neutral" empty="Nothing missing — every listed skill is on your resume." />

      {result.suggestions.length ? (
        <section aria-labelledby="sugg-heading">
          <h3 id="sugg-heading" className="text-sm font-semibold text-slate-900">
            Wording suggestions
          </h3>
          <ul className="mt-2 space-y-2 text-sm text-slate-700">
            {result.suggestions.map((s) => (
              <li key={s} className="rounded-md bg-slate-50 px-3 py-2">
                {s}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <div className="border-t border-slate-200 pt-4">
        <ApplyButton job={job} resumeVersionId={resumeVersionId} size="lg" className="w-full" />
      </div>
    </div>
  );
}

function SkillGroup({
  title,
  skills,
  variant,
  empty,
}: {
  title: string;
  skills: string[];
  variant: "green" | "neutral";
  empty: string;
}) {
  return (
    <section>
      <h3 className="text-sm font-semibold text-slate-900">{title}</h3>
      {skills.length ? (
        <ul className="mt-2 flex flex-wrap gap-2">
          {skills.map((skill) => (
            <li key={skill}>
              <Badge variant={variant}>{skill}</Badge>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-1 text-sm text-slate-500">{empty}</p>
      )}
    </section>
  );
}

function Spinner({ label }: { label: string }) {
  return (
    <p className="flex items-center justify-center gap-2 py-10 text-sm text-slate-600" role="status">
      <Loader2 className="h-5 w-5 animate-spin text-teal-600" aria-hidden /> {label}
    </p>
  );
}

function describe(error: unknown): string {
  if (error instanceof ApiError) return error.isUnauthorized ? "Please sign in again." : error.message;
  return error instanceof Error ? error.message : "Unexpected error";
}
