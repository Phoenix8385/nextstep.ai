"use client";

import { SessionProvider } from "next-auth/react";
import type { ReactNode } from "react";

import { Toaster } from "@/components/ui/toaster";

/** Client-side providers mounted once in the root layout. */
export function Providers({ children }: { children: ReactNode }) {
  return (
    <SessionProvider>
      {children}
      <Toaster />
    </SessionProvider>
  );
}
