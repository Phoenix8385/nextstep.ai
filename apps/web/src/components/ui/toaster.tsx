"use client";

import * as ToastPrimitive from "@radix-ui/react-toast";
import { X } from "lucide-react";

import { useToastStore, type ToastItem } from "@/hooks/use-toast";
import { cn } from "@/lib/utils";

const VARIANT_STYLES: Record<NonNullable<ToastItem["variant"]>, string> = {
  default: "border-slate-200 bg-white text-slate-900",
  success: "border-teal-200 bg-teal-50 text-teal-900",
  error: "border-red-200 bg-red-50 text-red-900",
};

/** Mount once in the root layout. Renders every toast in the store. */
export function Toaster() {
  const toasts = useToastStore((state) => state.toasts);
  const dismiss = useToastStore((state) => state.dismiss);
  const remove = useToastStore((state) => state.remove);

  return (
    <ToastPrimitive.Provider swipeDirection="right">
      {toasts.map((item) => (
        <ToastPrimitive.Root
          key={item.id}
          open={item.open}
          duration={item.duration === 0 ? Infinity : item.duration}
          onOpenChange={(open) => {
            if (!open) {
              dismiss(item.id);
              window.setTimeout(() => remove(item.id), 200);
            }
          }}
          className={cn(
            "pointer-events-auto flex w-full items-start gap-3 rounded-lg border p-4 shadow-lg",
            "data-[state=open]:animate-in data-[state=open]:slide-in-from-right-8",
            "data-[state=closed]:animate-out data-[state=closed]:fade-out-80",
            VARIANT_STYLES[item.variant ?? "default"],
          )}
        >
          <div className="flex-1">
            <ToastPrimitive.Title className="text-sm font-semibold">{item.title}</ToastPrimitive.Title>
            {item.description ? (
              <ToastPrimitive.Description className="mt-1 text-sm opacity-80">
                {item.description}
              </ToastPrimitive.Description>
            ) : null}
            {item.action ? (
              <ToastPrimitive.Action asChild altText={item.action.label}>
                <button
                  type="button"
                  onClick={() => void item.action?.onClick()}
                  className="mt-3 inline-flex items-center rounded-md bg-teal-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-teal-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
                >
                  {item.action.label}
                </button>
              </ToastPrimitive.Action>
            ) : null}
          </div>
          <ToastPrimitive.Close
            aria-label="Dismiss"
            className="rounded p-1 opacity-60 hover:opacity-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
          >
            <X className="h-4 w-4" aria-hidden />
          </ToastPrimitive.Close>
        </ToastPrimitive.Root>
      ))}
      <ToastPrimitive.Viewport className="fixed bottom-4 right-4 z-[100] flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-2 outline-none" />
    </ToastPrimitive.Provider>
  );
}
