/**
 * Types mirroring the FastAPI response models (services/api/app/schemas).
 * Keep field names snake_case to match the wire format exactly.
 */

export type WorkMode = "remote" | "hybrid" | "onsite";
export type ExperienceLevel = "intern" | "entry_level" | "experienced";

export interface JobSummary {
  id: string;
  company_name: string;
  title: string;
  location: string | null;
  work_mode: WorkMode | null;
  experience_level: ExperienceLevel | null;
  required_skills: string[];
  source_url: string;
  posted_at: string | null;
  detected_at: string;
  deadline: string | null;
  is_active: boolean;
  is_new: boolean;
}

export interface JobDetail extends JobSummary {
  external_job_id: string;
  source_name: string;
  description: string | null;
  requirements: string | null;
  eligibility: string | null;
  updated_at: string;
}

export interface JobPage {
  items: JobSummary[];
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
  has_next: boolean;
}

export interface SavedJob {
  id: string;
  saved_at: string;
  job: JobSummary;
}

export interface ResumeVersionSummary {
  id: string;
  version_number: number;
  parsed_skills: string[];
  created_at: string;
}

export interface ResumeVersion extends ResumeVersionSummary {
  resume_id: string;
  parsed_education: Record<string, unknown>[] | null;
  parsed_experience: Record<string, unknown>[] | null;
  parsed_projects: Record<string, unknown>[] | null;
  raw_text_chars: number;
}

export interface Resume {
  id: string;
  file_name: string;
  content_type: string;
  size_bytes: number;
  created_at: string;
  latest_version: ResumeVersionSummary | null;
}

export type EligibilityStatus = "likely_eligible" | "uncertain" | "not_eligible";

export interface MatchResult {
  match_score: number;
  matching_skills: string[];
  missing_skills: string[];
  eligibility_status: EligibilityStatus;
  eligibility_reasons: string[];
  suggestions: string[];
}

export interface AnalyzeResponse extends MatchResult {
  job_id: string;
  resume_version_id: string;
  profile_on_file: boolean;
}

export type ApplicationStatus =
  | "saved"
  | "applied_pending_confirmation"
  | "applied"
  | "screening"
  | "interview"
  | "offer"
  | "rejected"
  | "withdrawn";

export interface ApplicationEvent {
  id: number;
  event_type: string;
  event_time: string;
  details: string | null;
}

export interface Application {
  id: string;
  job: JobSummary;
  status: ApplicationStatus;
  match_score: string | number | null;
  resume_version_id: string | null;
  applied_at: string | null;
  notes: string | null;
  follow_up_date: string | null;
  created_at: string;
  updated_at: string;
  events: ApplicationEvent[];
}

export interface AuthUser {
  id: string;
  email: string;
  full_name: string;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  user: AuthUser;
}
