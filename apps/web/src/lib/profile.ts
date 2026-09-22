/**
 * Academic profile and career preferences (`/profile`).
 *
 * The profile is what makes eligibility checks meaningful: `graduation_year`,
 * `experience_level` and `cgpa` are compared against what a posting states
 * (see services/api/app/services/matching.py). Without it every job comes back
 * "uncertain", so onboarding asks for these up front.
 */

import { api, ApiError } from "@/lib/api-client";
import type { ProfileUpdate, UserProfile } from "@/types/api";

/** The current user's profile, or `null` when they have not created one yet. */
export async function getProfile(): Promise<UserProfile | null> {
  try {
    return await api.get<UserProfile>("/profile");
  } catch (error) {
    // 404 is the documented "no profile yet" answer, not a failure.
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  }
}

/** Create or merge the profile. Only the fields present in `patch` are written. */
export async function saveProfile(patch: ProfileUpdate): Promise<UserProfile> {
  return api.put<UserProfile>("/profile", patch);
}

/** Split a comma/newline separated field into a clean list (the API de-duplicates too). */
export function parseList(value: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of value.split(/[,\n]/)) {
    const item = raw.trim();
    const key = item.toLowerCase();
    if (item && !seen.has(key)) {
      seen.add(key);
      out.push(item);
    }
  }
  return out;
}

/** `true` when the profile has enough in it for eligibility checks to say anything. */
export function isProfileComplete(profile: UserProfile | null): boolean {
  return Boolean(profile && profile.graduation_year !== null && profile.skills.length > 0);
}
