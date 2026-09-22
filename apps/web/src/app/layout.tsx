import type { Metadata } from "next";
import localFont from "next/font/local";
import type { ReactNode } from "react";

import { TopBar } from "@/components/layout/TopBar";
import { Providers } from "@/components/providers";

import "./globals.css";

const geistSans = localFont({
  src: "./fonts/GeistVF.woff",
  variable: "--font-geist-sans",
  weight: "100 900",
});

export const metadata: Metadata = {
  title: "NextStep.ai",
  description: "Job discovery, transparent resume matching, and application tracking.",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en" className={geistSans.variable}>
      <body className="min-h-screen bg-slate-50 font-sans text-slate-900 antialiased">
        <Providers>
          <TopBar />
          <main className="mx-auto w-full max-w-6xl px-4 py-6">{children}</main>
        </Providers>
      </body>
    </html>
  );
}
