import { cva, type VariantProps } from "class-variance-authority";
import type { HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium whitespace-nowrap",
  {
    variants: {
      variant: {
        neutral: "border-slate-200 bg-slate-100 text-slate-700",
        outline: "border-slate-300 bg-transparent text-slate-700",
        teal: "border-teal-200 bg-teal-100 text-teal-800",
        green: "border-green-200 bg-green-100 text-green-800",
        yellow: "border-amber-200 bg-amber-100 text-amber-800",
        red: "border-red-200 bg-red-100 text-red-800",
        blue: "border-sky-200 bg-sky-100 text-sky-800",
      },
    },
    defaultVariants: { variant: "neutral" },
  },
);

/** The visual tones a Badge can take. */
export type BadgeVariant = NonNullable<VariantProps<typeof badgeVariants>["variant"]>;

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}
