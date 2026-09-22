"use client";

import * as SelectPrimitive from "@radix-ui/react-select";
import { Check, ChevronDown } from "lucide-react";

import { cn } from "@/lib/utils";

export interface SelectOption<T extends string> {
  value: T;
  label: string;
}

interface SelectProps<T extends string> {
  id?: string;
  value: T;
  onChange: (value: T) => void;
  options: readonly SelectOption<T>[];
  "aria-label": string;
  className?: string;
}

/** Radix Select with a plain look; `value` must be one of `options`. */
export function Select<T extends string>({ id, value, onChange, options, className, ...aria }: SelectProps<T>) {
  return (
    <SelectPrimitive.Root value={value} onValueChange={(next) => onChange(next as T)}>
      <SelectPrimitive.Trigger
        id={id}
        aria-label={aria["aria-label"]}
        className={cn(
          "inline-flex h-10 w-full items-center justify-between rounded-md border border-slate-300 bg-white px-3 text-sm text-slate-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500",
          className,
        )}
      >
        <SelectPrimitive.Value />
        <SelectPrimitive.Icon>
          <ChevronDown className="h-4 w-4 opacity-60" aria-hidden />
        </SelectPrimitive.Icon>
      </SelectPrimitive.Trigger>
      <SelectPrimitive.Portal>
        <SelectPrimitive.Content
          position="popper"
          sideOffset={4}
          className="z-50 min-w-[var(--radix-select-trigger-width)] overflow-hidden rounded-md border border-slate-200 bg-white shadow-md"
        >
          <SelectPrimitive.Viewport className="p-1">
            {options.map((option) => (
              <SelectPrimitive.Item
                key={option.value}
                value={option.value}
                className="relative flex cursor-pointer select-none items-center rounded-sm py-1.5 pl-8 pr-3 text-sm text-slate-900 outline-none data-[highlighted]:bg-teal-50 data-[state=checked]:font-semibold"
              >
                <SelectPrimitive.ItemIndicator className="absolute left-2 inline-flex items-center">
                  <Check className="h-4 w-4 text-teal-600" aria-hidden />
                </SelectPrimitive.ItemIndicator>
                <SelectPrimitive.ItemText>{option.label}</SelectPrimitive.ItemText>
              </SelectPrimitive.Item>
            ))}
          </SelectPrimitive.Viewport>
        </SelectPrimitive.Content>
      </SelectPrimitive.Portal>
    </SelectPrimitive.Root>
  );
}
