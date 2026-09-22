"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { SlidersHorizontal, X } from "lucide-react";
import { useId } from "react";

import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { hasActiveFilters, type JobFilters } from "@/store/jobs";

const WORK_MODE_OPTIONS = [
  { value: "any", label: "Any work mode" },
  { value: "remote", label: "Remote" },
  { value: "hybrid", label: "Hybrid" },
  { value: "onsite", label: "On-site" },
] as const;

const EXPERIENCE_OPTIONS = [
  { value: "any", label: "Any level" },
  { value: "intern", label: "Internship" },
  { value: "entry_level", label: "Entry-level" },
  { value: "experienced", label: "Experienced" },
] as const;

type WorkModeValue = (typeof WORK_MODE_OPTIONS)[number]["value"];
type ExperienceValue = (typeof EXPERIENCE_OPTIONS)[number]["value"];

export interface FilterBarProps {
  filters: JobFilters;
  onChange: (patch: Partial<JobFilters>) => void;
  onClear: () => void;
  resultCount?: number;
}

/**
 * Sticky filter bar. On `md+` the controls sit inline; on smaller screens they
 * collapse into a "Filters" button that opens a bottom drawer.
 */
export function FilterBar({ filters, onChange, onClear, resultCount }: FilterBarProps) {
  const active = hasActiveFilters(filters);
  const activeCount = Object.values(filters).filter((v) => v.trim() !== "").length;

  return (
    <div className="sticky top-14 z-30 -mx-4 border-b border-slate-200 bg-slate-50/95 px-4 py-3 backdrop-blur">
      {/* Desktop / tablet */}
      <div className="hidden md:block">
        <Controls filters={filters} onChange={onChange} onClear={onClear} active={active} />
      </div>

      {/* Mobile */}
      <div className="flex items-center justify-between gap-3 md:hidden">
        <p className="text-sm text-slate-600">
          {resultCount !== undefined ? `${resultCount.toLocaleString()} jobs` : "Jobs"}
        </p>
        <Dialog.Root>
          <Dialog.Trigger asChild>
            <Button variant="outline" size="sm">
              <SlidersHorizontal className="h-4 w-4" aria-hidden />
              Filters{activeCount ? ` (${activeCount})` : ""}
            </Button>
          </Dialog.Trigger>
          <Dialog.Portal>
            <Dialog.Overlay className="fixed inset-0 z-40 bg-black/40" />
            <Dialog.Content
              className="fixed inset-x-0 bottom-0 z-50 max-h-[85vh] overflow-y-auto rounded-t-2xl bg-white p-5 shadow-2xl focus:outline-none"
              aria-describedby={undefined}
            >
              <div className="mb-4 flex items-center justify-between">
                <Dialog.Title className="text-base font-semibold">Filter jobs</Dialog.Title>
                <Dialog.Close asChild>
                  <Button variant="ghost" size="icon" aria-label="Close filters">
                    <X className="h-5 w-5" aria-hidden />
                  </Button>
                </Dialog.Close>
              </div>
              <Controls filters={filters} onChange={onChange} onClear={onClear} active={active} stacked />
              <Dialog.Close asChild>
                <Button className="mt-4 w-full">Show results</Button>
              </Dialog.Close>
            </Dialog.Content>
          </Dialog.Portal>
        </Dialog.Root>
      </div>
    </div>
  );
}

interface ControlsProps extends Omit<FilterBarProps, "resultCount"> {
  active: boolean;
  stacked?: boolean;
}

function Controls({ filters, onChange, onClear, active, stacked = false }: ControlsProps) {
  const ids = useId();
  const inputClass =
    "h-10 w-full rounded-md border border-slate-300 bg-white px-3 text-sm placeholder:text-slate-400 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500";

  return (
    <div className={stacked ? "grid grid-cols-1 gap-3" : "grid grid-cols-2 gap-3 lg:grid-cols-6"}>
      <div className={stacked ? "" : "col-span-2 lg:col-span-2"}>
        <label htmlFor={`${ids}-role`} className="sr-only">
          Role
        </label>
        <input
          id={`${ids}-role`}
          type="search"
          placeholder="Search role (e.g. backend engineer)"
          value={filters.role}
          onChange={(e) => onChange({ role: e.target.value })}
          className={inputClass}
        />
      </div>
      <div>
        <label htmlFor={`${ids}-company`} className="sr-only">
          Company
        </label>
        <input
          id={`${ids}-company`}
          placeholder="Company"
          value={filters.company}
          onChange={(e) => onChange({ company: e.target.value })}
          className={inputClass}
        />
      </div>
      <div>
        <label htmlFor={`${ids}-location`} className="sr-only">
          Location
        </label>
        <input
          id={`${ids}-location`}
          placeholder="Location"
          value={filters.location}
          onChange={(e) => onChange({ location: e.target.value })}
          className={inputClass}
        />
      </div>
      <Select<WorkModeValue>
        aria-label="Work mode"
        value={filters.work_mode === "" ? "any" : filters.work_mode}
        onChange={(v) => onChange({ work_mode: v === "any" ? "" : v })}
        options={WORK_MODE_OPTIONS}
      />
      <div className="flex gap-2">
        <Select<ExperienceValue>
          aria-label="Experience level"
          value={filters.experience_level === "" ? "any" : filters.experience_level}
          onChange={(v) => onChange({ experience_level: v === "any" ? "" : v })}
          options={EXPERIENCE_OPTIONS}
          className="flex-1"
        />
        <Button variant="ghost" size="md" onClick={onClear} disabled={!active} className="shrink-0">
          Clear
        </Button>
      </div>
    </div>
  );
}
