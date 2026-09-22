"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useSession } from "next-auth/react";
import { Suspense, useEffect, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { toast } from "@/hooks/use-toast";
import { ApiError } from "@/lib/api-client";
import { getProfile, parseList, saveProfile } from "@/lib/profile";
import type { ProfileUpdate } from "@/types/api";

/** Mirrors the bounds enforced by schemas/profile.py. */
const CGPA_MAX = 9.99;
const GRAD_YEAR_MIN = 1950;
const GRAD_YEAR_MAX = 2100;

const EXPERIENCE_OPTIONS = [
  { value: "student", label: "Student (still enrolled)" },
  { value: "fresher", label: "Fresher / new graduate" },
  { value: "entry_level", label: "Entry-level (0-2 years)" },
  { value: "experienced", label: "Experienced (2+ years)" },
] as const;

type ExperienceValue = (typeof EXPERIENCE_OPTIONS)[number]["value"];

const INPUT_CLASS =
  "mt-1 h-10 w-full rounded-md border border-slate-300 bg-white px-3 text-sm placeholder:text-slate-400 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500";

interface FormState {
  college: string;
  branch: string;
  cgpa: string;
  graduationYear: string;
  experienceLevel: ExperienceValue;
  skills: string;
  preferredRoles: string;
  preferredLocations: string;
}

const EMPTY_FORM: FormState = {
  college: "",
  branch: "",
  cgpa: "",
  graduationYear: "",
  experienceLevel: "student",
  skills: "",
  preferredRoles: "",
  preferredLocations: "",
};

function OnboardingForm() {
  const router = useRouter();
  const params = useSearchParams();
  const { status } = useSession();
  const next = params.get("next") ?? "/jobs";

  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (status === "unauthenticated") {
      router.replace(`/login?callbackUrl=${encodeURIComponent("/onboarding")}`);
    }
  }, [status, router]);

  // Prefill from an existing profile so this page doubles as "edit profile".
  useEffect(() => {
    if (status !== "authenticated") return;
    let cancelled = false;
    void (async () => {
      try {
        const profile = await getProfile();
        if (cancelled || !profile) return;
        setForm({
          college: profile.college ?? "",
          branch: profile.branch ?? "",
          cgpa: profile.cgpa === null ? "" : String(profile.cgpa),
          graduationYear: profile.graduation_year === null ? "" : String(profile.graduation_year),
          experienceLevel:
            EXPERIENCE_OPTIONS.find((o) => o.value === profile.experience_level)?.value ?? "student",
          skills: profile.skills.join(", "),
          preferredRoles: profile.preferred_roles.join(", "),
          preferredLocations: profile.preferred_locations.join(", "),
        });
      } catch (caught) {
        if (!cancelled) {
          setError(caught instanceof ApiError ? caught.message : "Could not load your profile");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [status]);

  function set<K extends keyof FormState>(key: K, value: FormState[K]): void {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function validate(): string | null {
    if (form.cgpa.trim()) {
      const cgpa = Number(form.cgpa);
      if (Number.isNaN(cgpa) || cgpa < 0 || cgpa > CGPA_MAX) {
        return `CGPA must be between 0 and ${CGPA_MAX}`;
      }
    }
    if (form.graduationYear.trim()) {
      const year = Number(form.graduationYear);
      if (!Number.isInteger(year) || year < GRAD_YEAR_MIN || year > GRAD_YEAR_MAX) {
        return `Graduation year must be between ${GRAD_YEAR_MIN} and ${GRAD_YEAR_MAX}`;
      }
    }
    return null;
  }

  function toPayload(): ProfileUpdate {
    return {
      college: form.college.trim() || null,
      branch: form.branch.trim() || null,
      // Sent as a string so the NUMERIC(3,2) column keeps exactly what was typed.
      cgpa: form.cgpa.trim() || null,
      graduation_year: form.graduationYear.trim() ? Number(form.graduationYear) : null,
      experience_level: form.experienceLevel,
      skills: parseList(form.skills),
      preferred_roles: parseList(form.preferredRoles),
      preferred_locations: parseList(form.preferredLocations),
    };
  }

  async function onSubmit(event: FormEvent): Promise<void> {
    event.preventDefault();
    const invalid = validate();
    if (invalid) {
      setError(invalid);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await saveProfile(toPayload());
      toast({
        title: "Profile saved",
        description: "Eligibility checks will now use your graduation year and CGPA.",
        variant: "success",
      });
      router.push(next);
      router.refresh();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not save your profile");
    } finally {
      setSaving(false);
    }
  }

  if (status === "loading" || (status === "authenticated" && loading)) {
    return (
      <div
        className="mx-auto mt-10 h-96 w-full max-w-2xl animate-pulse rounded-xl bg-white"
        aria-hidden
      />
    );
  }
  if (status !== "authenticated") return null;

  return (
    <div className="mx-auto mt-6 w-full max-w-2xl">
      <h1 className="text-2xl font-bold tracking-tight">Tell us about yourself</h1>
      <p className="mt-1 text-sm text-slate-600">
        We compare this with what each posting actually states — nothing is inferred or invented.
        You can change it any time.
      </p>

      <form onSubmit={onSubmit} className="mt-6 space-y-6" noValidate>
        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="text-base font-semibold">Education</h2>
          <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
            <label className="block text-sm sm:col-span-2">
              <span className="font-medium">College</span>
              <input
                value={form.college}
                onChange={(e) => set("college", e.target.value)}
                placeholder="e.g. BMS College of Engineering"
                maxLength={255}
                className={INPUT_CLASS}
              />
            </label>
            <label className="block text-sm">
              <span className="font-medium">Branch</span>
              <input
                value={form.branch}
                onChange={(e) => set("branch", e.target.value)}
                placeholder="e.g. Computer Science"
                maxLength={255}
                className={INPUT_CLASS}
              />
            </label>
            <label className="block text-sm">
              <span className="font-medium">CGPA</span>
              <input
                type="number"
                inputMode="decimal"
                step="0.01"
                min={0}
                max={CGPA_MAX}
                value={form.cgpa}
                onChange={(e) => set("cgpa", e.target.value)}
                placeholder="e.g. 8.45"
                className={INPUT_CLASS}
              />
              <span className="mt-1 block text-xs text-slate-500">On a 10-point scale.</span>
            </label>
            <label className="block text-sm">
              <span className="font-medium">Graduation year</span>
              <input
                type="number"
                inputMode="numeric"
                step="1"
                min={GRAD_YEAR_MIN}
                max={GRAD_YEAR_MAX}
                value={form.graduationYear}
                onChange={(e) => set("graduationYear", e.target.value)}
                placeholder="e.g. 2027"
                className={INPUT_CLASS}
              />
            </label>
            <div className="block text-sm">
              <span className="font-medium">Where you are now</span>
              <Select<ExperienceValue>
                aria-label="Experience level"
                value={form.experienceLevel}
                onChange={(value) => set("experienceLevel", value)}
                options={EXPERIENCE_OPTIONS}
                className="mt-1"
              />
            </div>
          </div>
        </section>

        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="text-base font-semibold">Skills</h2>
          <p className="mt-1 text-xs text-slate-500">
            Comma separated. These are matched literally against each posting&apos;s required
            skills.
          </p>
          <label className="mt-3 block text-sm">
            <span className="sr-only">Skills</span>
            <textarea
              value={form.skills}
              onChange={(e) => set("skills", e.target.value)}
              rows={3}
              placeholder="Python, FastAPI, React, PostgreSQL, Docker"
              className="mt-1 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm placeholder:text-slate-400 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
            />
          </label>
        </section>

        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="text-base font-semibold">
            Preferences <span className="font-normal text-slate-500">(optional)</span>
          </h2>
          <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
            <label className="block text-sm">
              <span className="font-medium">Preferred roles</span>
              <input
                value={form.preferredRoles}
                onChange={(e) => set("preferredRoles", e.target.value)}
                placeholder="Backend Engineer, Data Analyst"
                className={INPUT_CLASS}
              />
            </label>
            <label className="block text-sm">
              <span className="font-medium">Preferred locations</span>
              <input
                value={form.preferredLocations}
                onChange={(e) => set("preferredLocations", e.target.value)}
                placeholder="Bengaluru, Remote"
                className={INPUT_CLASS}
              />
            </label>
          </div>
        </section>

        {error ? (
          <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </p>
        ) : null}

        <div className="flex items-center gap-3">
          <Button type="submit" size="lg" disabled={saving}>
            {saving ? "Saving…" : "Save and browse jobs"}
          </Button>
          <Button type="button" variant="ghost" onClick={() => router.push(next)} disabled={saving}>
            Skip for now
          </Button>
        </div>
      </form>
    </div>
  );
}

export default function OnboardingPage() {
  return (
    <Suspense fallback={null}>
      <OnboardingForm />
    </Suspense>
  );
}
