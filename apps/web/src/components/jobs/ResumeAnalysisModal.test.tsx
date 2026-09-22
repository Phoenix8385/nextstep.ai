import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, api: { get: vi.fn(), post: vi.fn(), delete: vi.fn(), put: vi.fn(), patch: vi.fn() } };
});
vi.mock("next-auth/react", () => ({ useSession: () => ({ status: "authenticated", data: null }) }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/jobs/job-1",
}));

import { api } from "@/lib/api-client";
import { ResumeAnalysisModal, scoreColor } from "@/components/jobs/ResumeAnalysisModal";
import type { AnalyzeResponse, JobDetail, Resume, ResumeVersion } from "@/types/api";

const JOB: JobDetail = {
  id: "job-1",
  company_name: "Acme",
  title: "Backend Engineer",
  location: "Remote",
  work_mode: "remote",
  experience_level: "entry_level",
  required_skills: ["Python", "PostgreSQL", "Docker"],
  source_url: "https://example.com/apply",
  posted_at: "2026-09-20T12:00:00Z",
  detected_at: "2026-09-20T12:00:00Z",
  deadline: null,
  is_active: true,
  is_new: false,
  external_job_id: "1",
  source_name: "greenhouse",
  description: "Build things.",
  requirements: null,
  eligibility: null,
  updated_at: "2026-09-20T12:00:00Z",
};

const RESUME: Resume = {
  id: "resume-1",
  file_name: "ada.pdf",
  content_type: "application/pdf",
  size_bytes: 1000,
  created_at: "2026-09-20T12:00:00Z",
  latest_version: {
    id: "version-1",
    version_number: 1,
    parsed_skills: ["Python", "Docker"],
    created_at: "2026-09-20T12:00:00Z",
  },
};

function analysis(overrides: Partial<AnalyzeResponse> = {}): AnalyzeResponse {
  return {
    job_id: JOB.id,
    resume_version_id: "version-1",
    profile_on_file: true,
    match_score: 67,
    scoreable: true,
    matching_skills: ["Python", "Docker"],
    missing_skills: ["PostgreSQL"],
    eligibility_status: "likely_eligible",
    eligibility_reasons: ["Entry-level role matching your experience level."],
    suggestions: ["Lead with Python, Docker in your summary or skills section."],
    ...overrides,
  };
}

function renderModal(onOpenChange = vi.fn()) {
  return { onOpenChange, ...render(<ResumeAnalysisModal job={JOB} open onOpenChange={onOpenChange} />) };
}

beforeEach(() => {
  vi.mocked(api.get).mockReset();
  vi.mocked(api.post).mockReset();
});

describe("scoreColor thresholds", () => {
  it("is green at 70+, amber 40-69, red below 40", () => {
    expect(scoreColor(100).ring).toContain("green");
    expect(scoreColor(70).ring).toContain("green");
    expect(scoreColor(69).ring).toContain("amber");
    expect(scoreColor(40).ring).toContain("amber");
    expect(scoreColor(39).ring).toContain("red");
    expect(scoreColor(0).ring).toContain("red");
  });
});

describe("step 1 — choosing a resume", () => {
  it("offers the resume on file and analyzes with its latest version", async () => {
    const user = userEvent.setup();
    vi.mocked(api.get).mockResolvedValueOnce([RESUME]);
    vi.mocked(api.post).mockResolvedValueOnce(analysis());

    renderModal();

    const useExisting = await screen.findByRole("button", { name: /use my resume on file/i });
    expect(screen.getByText("ada.pdf")).toBeInTheDocument();
    await user.click(useExisting);

    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith("/jobs/job-1/analyze", { resume_version_id: "version-1" }),
    );
    expect(await screen.findByText("67%")).toBeInTheDocument();
  });

  it("shows the dropzone when there is no resume, and uploads then parses then analyzes", async () => {
    const user = userEvent.setup();
    vi.mocked(api.get).mockResolvedValueOnce([]);
    const version: ResumeVersion = {
      ...RESUME.latest_version!,
      resume_id: "resume-9",
      parsed_education: null,
      parsed_experience: null,
      parsed_projects: null,
      raw_text_chars: 500,
      id: "version-9",
    };
    vi.mocked(api.post)
      .mockResolvedValueOnce({ ...RESUME, id: "resume-9" }) // POST /resumes
      .mockResolvedValueOnce(version) // POST /resumes/{id}/parse
      .mockResolvedValueOnce(analysis({ resume_version_id: "version-9" })); // POST /jobs/{id}/analyze

    renderModal();

    expect(await screen.findByText(/drop your resume here/i)).toBeInTheDocument();
    const input = screen.getByLabelText(/choose resume file/i);
    await user.upload(input, new File(["%PDF-"], "cv.pdf", { type: "application/pdf" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(3));
    const [uploadPath, body] = vi.mocked(api.post).mock.calls[0];
    expect(uploadPath).toBe("/resumes");
    expect(body).toBeInstanceOf(FormData);
    expect(vi.mocked(api.post).mock.calls[1][0]).toBe("/resumes/resume-9/parse");
    expect(vi.mocked(api.post).mock.calls[2]).toEqual([
      "/jobs/job-1/analyze",
      { resume_version_id: "version-9" },
    ]);
  });

  it("rejects a non-PDF/DOCX file dropped on the zone", async () => {
    // The file picker already filters by `accept`; drag-and-drop does not, so
    // that is the path where the type check actually has to hold.
    vi.mocked(api.get).mockResolvedValueOnce([]);

    renderModal();

    const dropzone = await screen.findByText(/drop your resume here/i);
    fireEvent.drop(dropzone.closest("[role=button]")!, {
      dataTransfer: { files: [new File(["hi"], "notes.txt", { type: "text/plain" })] },
    });

    expect(await screen.findByText(/please choose a pdf or docx file/i)).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });

  it("rejects a file over 5 MB", async () => {
    vi.mocked(api.get).mockResolvedValueOnce([]);

    renderModal();

    const dropzone = await screen.findByText(/drop your resume here/i);
    const big = new File(["x"], "big.pdf", { type: "application/pdf" });
    Object.defineProperty(big, "size", { value: 6 * 1024 * 1024 });
    fireEvent.drop(dropzone.closest("[role=button]")!, { dataTransfer: { files: [big] } });

    expect(await screen.findByText(/larger than 5 MB/i)).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });
});

describe("step 2 — results", () => {
  beforeEach(() => {
    vi.mocked(api.get).mockResolvedValue([RESUME]);
  });

  async function analyzeWith(result: AnalyzeResponse) {
    const user = userEvent.setup();
    vi.mocked(api.post).mockResolvedValueOnce(result);
    renderModal();
    await user.click(await screen.findByRole("button", { name: /use my resume on file/i }));
    // An unscoreable posting renders "No score" in place of the percentage.
    await screen.findByText(result.scoreable ? `${result.match_score}%` : "No score");
    return user;
  }

  it("renders the score, eligibility badge with reasons, chips and suggestions", async () => {
    await analyzeWith(analysis());

    expect(screen.getByRole("img", { name: /match score 67 percent/i })).toBeInTheDocument();
    expect(screen.getByText("Likely Eligible")).toBeInTheDocument();
    expect(screen.getByText(/entry-level role matching your experience level/i)).toBeInTheDocument();

    const matching = screen.getByRole("heading", { name: /matching skills/i }).parentElement!;
    expect(within(matching).getByText("Python")).toBeInTheDocument();
    expect(within(matching).getByText("Docker")).toBeInTheDocument();

    const missing = screen.getByRole("heading", { name: /not found on your resume/i }).parentElement!;
    expect(within(missing).getByText("PostgreSQL")).toBeInTheDocument();

    expect(screen.getByRole("heading", { name: /wording suggestions/i })).toBeInTheDocument();
    expect(screen.getByText(/lead with python, docker/i)).toBeInTheDocument();
  });

  it("colours the ring by score band", async () => {
    await analyzeWith(analysis({ match_score: 85 }));
    expect(document.querySelector(".stroke-green-500")).not.toBeNull();
  });

  it("shows Not Eligible with its reasons", async () => {
    await analyzeWith(
      analysis({
        match_score: 20,
        eligibility_status: "not_eligible",
        eligibility_reasons: ["Posting targets graduates of 2026; your graduation year is 2029."],
        matching_skills: [],
        missing_skills: ["Python", "PostgreSQL", "Docker"],
      }),
    );
    expect(screen.getByText("Not Eligible")).toBeInTheDocument();
    expect(screen.getByText(/your graduation year is 2029/i)).toBeInTheDocument();
    expect(screen.getByText(/none of the listed skills were found/i)).toBeInTheDocument();
    expect(document.querySelector(".stroke-red-500")).not.toBeNull();
  });

  it("says the posting cannot be scored instead of showing a 0% ring", async () => {
    // A posting that names no identifiable skills scores 0 for everyone, so a
    // "0%" ring would read as a bad fit rather than a missing input.
    await analyzeWith(
      analysis({
        scoreable: false,
        match_score: 0,
        matching_skills: [],
        missing_skills: [],
        suggestions: ["This posting lists no identifiable skills, so the score is not meaningful."],
      }),
    );

    expect(screen.getByRole("img", { name: /no match score/i })).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /match score \d+ percent/i })).not.toBeInTheDocument();
    expect(screen.getByText(/does not list skills we can identify/i)).toBeInTheDocument();
    // The misleading empty-state copy must not appear either.
    expect(screen.queryByText(/none of the listed skills were found/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/every listed skill is on your resume/i)).not.toBeInTheDocument();
  });

  it("still shows a real 0% when the posting lists skills the resume lacks", async () => {
    await analyzeWith(
      analysis({ scoreable: true, match_score: 0, matching_skills: [], missing_skills: ["Rust"] }),
    );

    expect(screen.getByRole("img", { name: /match score 0 percent/i })).toBeInTheDocument();
    expect(screen.getByText(/none of the listed skills were found/i)).toBeInTheDocument();
  });

  it("prompts to complete the profile when there is none", async () => {
    await analyzeWith(analysis({ profile_on_file: false, eligibility_status: "uncertain" }));
    expect(screen.getByText("Uncertain")).toBeInTheDocument();
    expect(screen.getByText(/add graduation year and experience level/i)).toBeInTheDocument();
  });

  it("offers Apply Now at the bottom, which opens the posting in a new tab", async () => {
    const open = vi.fn();
    vi.stubGlobal("open", open);
    const user = await analyzeWith(analysis());

    await user.click(screen.getByRole("button", { name: /apply now/i }));

    expect(open).toHaveBeenCalledWith("https://example.com/apply", "_blank", "noopener,noreferrer");
    // Same behaviour as the page-level button: it becomes "Mark as Applied".
    expect(await screen.findByRole("button", { name: /mark as applied/i })).toBeInTheDocument();
    vi.unstubAllGlobals();
  });
});

describe("accessibility", () => {
  it("is a labelled modal dialog that traps focus", async () => {
    vi.mocked(api.get).mockResolvedValueOnce([RESUME]);
    renderModal();

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveAccessibleName(/resume analysis/i);
    expect(dialog).toHaveAccessibleDescription(/backend engineer at acme/i);
    // Radix marks everything outside the dialog inert while it is open.
    await waitFor(() => expect(document.body).toHaveAttribute("data-scroll-locked"));
    await waitFor(() => expect(dialog.contains(document.activeElement)).toBe(true));
  });

  it("closes on Escape and via the close button", async () => {
    const user = userEvent.setup();
    vi.mocked(api.get).mockResolvedValue([RESUME]);

    const { onOpenChange } = renderModal();
    await screen.findByRole("dialog");

    await user.keyboard("{Escape}");
    expect(onOpenChange).toHaveBeenCalledWith(false);

    onOpenChange.mockClear();
    await user.click(screen.getByRole("button", { name: /close/i }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});
