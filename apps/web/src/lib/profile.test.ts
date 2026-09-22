import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
  };
});

import { api, ApiError } from "@/lib/api-client";
import { getProfile, isProfileComplete, parseList, saveProfile } from "@/lib/profile";
import type { UserProfile } from "@/types/api";

const PROFILE: UserProfile = {
  user_id: "user-1",
  college: "BMS College of Engineering",
  branch: "Computer Science",
  cgpa: "8.60",
  graduation_year: 2027,
  experience_level: "student",
  preferred_roles: ["Backend Engineer"],
  preferred_locations: ["Bengaluru"],
  preferred_work_mode: [],
  skills: ["Python", "FastAPI"],
};

beforeEach(() => {
  vi.mocked(api.get).mockReset();
  vi.mocked(api.put).mockReset().mockResolvedValue(PROFILE);
});

describe("getProfile", () => {
  it("returns the profile", async () => {
    vi.mocked(api.get).mockResolvedValue(PROFILE);
    await expect(getProfile()).resolves.toEqual(PROFILE);
    expect(api.get).toHaveBeenCalledWith("/profile");
  });

  it("treats 404 as 'no profile yet' rather than an error", async () => {
    vi.mocked(api.get).mockRejectedValue(new ApiError(404, "Profile not created yet"));
    await expect(getProfile()).resolves.toBeNull();
  });

  it("still propagates other failures", async () => {
    vi.mocked(api.get).mockRejectedValue(new ApiError(500, "boom"));
    await expect(getProfile()).rejects.toBeInstanceOf(ApiError);
  });
});

describe("saveProfile", () => {
  it("PUTs only the fields it is given", async () => {
    await saveProfile({ cgpa: "9.10" });
    expect(api.put).toHaveBeenCalledWith("/profile", { cgpa: "9.10" });
  });

  it("sends cleared scalars as null and cleared lists as []", async () => {
    await saveProfile({ college: null, skills: [] });
    expect(api.put).toHaveBeenCalledWith("/profile", { college: null, skills: [] });
  });
});

describe("parseList", () => {
  it("splits on commas and newlines and trims", () => {
    expect(parseList(" Python , FastAPI \n React ")).toEqual(["Python", "FastAPI", "React"]);
  });

  it("drops blanks and de-duplicates case-insensitively, keeping the first spelling", () => {
    expect(parseList("Python,, python ,PYTHON,SQL")).toEqual(["Python", "SQL"]);
  });

  it("returns an empty list for empty input", () => {
    expect(parseList("   ")).toEqual([]);
  });
});

describe("isProfileComplete", () => {
  it("is false without a profile", () => {
    expect(isProfileComplete(null)).toBe(false);
  });

  it("needs both a graduation year and at least one skill", () => {
    expect(isProfileComplete({ ...PROFILE, graduation_year: null })).toBe(false);
    expect(isProfileComplete({ ...PROFILE, skills: [] })).toBe(false);
    expect(isProfileComplete(PROFILE)).toBe(true);
  });
});
