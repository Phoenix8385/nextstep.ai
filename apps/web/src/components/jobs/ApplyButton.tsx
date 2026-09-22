"use client";

import { Check, ExternalLink } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useSession } from "next-auth/react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { toast } from "@/hooks/use-toast";
import { ApiError } from "@/lib/api-client";
import { markAsApplied, openSourceUrl } from "@/lib/applications";
import type { JobSummary } from "@/types/api";

export interface ApplyButtonProps {
  job: Pick<JobSummary, "id" | "source_url" | "title" | "company_name">;
  /** Resume version to attach so the match score is stored with the application. */
  resumeVersionId?: string | null;
  size?: "md" | "lg";
  className?: string;
  /** Called after the application is recorded (both page and modal can react). */
  onApplied?: () => void;
}

type Phase = "idle" | "opened" | "saving" | "applied";

/**
 * "Apply Now" → opens the employer's posting in a new tab and shows a toast
 * with an inline "Mark as Applied" action; the button itself then turns into
 * "Mark as Applied" until the user confirms.
 */
export function ApplyButton({ job, resumeVersionId, size = "md", className, onApplied }: ApplyButtonProps) {
  const [phase, setPhase] = useState<Phase>("idle");
  const { status } = useSession();
  const router = useRouter();
  const pathname = usePathname();

  function requireSignIn(): boolean {
    if (status === "authenticated") return true;
    router.push(`/login?callbackUrl=${encodeURIComponent(pathname)}`);
    return false;
  }

  async function confirmApplied(): Promise<void> {
    if (!requireSignIn()) return;
    setPhase("saving");
    try {
      await markAsApplied(job.id, resumeVersionId);
      setPhase("applied");
      toast({
        title: "Marked as applied",
        description: `${job.title} at ${job.company_name} is now in your tracker.`,
        variant: "success",
      });
      onApplied?.();
    } catch (error) {
      setPhase("opened");
      toast({
        title: "Could not record the application",
        description: error instanceof ApiError ? error.message : "Please try again.",
        variant: "error",
      });
    }
  }

  function applyNow(): void {
    openSourceUrl(job.source_url);
    setPhase("opened");
    toast({
      title: "Don't forget to mark this as applied once you've submitted it",
      description: `${job.company_name} — ${job.title}`,
      duration: 0,
      action: { label: "Mark as Applied", onClick: confirmApplied },
    });
  }

  if (phase === "applied") {
    return (
      <Button variant="success" size={size} className={className} disabled aria-live="polite">
        <Check className="h-4 w-4" aria-hidden />
        Applied
      </Button>
    );
  }

  if (phase === "opened" || phase === "saving") {
    return (
      <Button
        variant="secondary"
        size={size}
        className={className}
        onClick={() => void confirmApplied()}
        disabled={phase === "saving"}
      >
        {phase === "saving" ? "Saving…" : "Mark as Applied"}
      </Button>
    );
  }

  return (
    <Button variant="primary" size={size} className={className} onClick={applyNow}>
      Apply Now
      <ExternalLink className="h-4 w-4" aria-hidden />
    </Button>
  );
}
