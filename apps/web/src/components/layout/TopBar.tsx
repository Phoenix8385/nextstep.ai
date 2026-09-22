"use client";

import { ChevronDown, LogOut, User as UserIcon } from "lucide-react";
import Link from "next/link";
import { signOut, useSession } from "next-auth/react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { clearTokenCache } from "@/lib/api-client";

/** Site header: brand on the left, user menu (or sign-in) on the right. */
export function TopBar() {
  const { data: session, status } = useSession();
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (event: MouseEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <header className="sticky top-0 z-40 border-b border-slate-200 bg-white/95 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4">
        <Link href="/jobs" className="flex items-center gap-2 text-lg font-bold tracking-tight text-slate-900">
          <span className="inline-block h-6 w-6 rounded-md bg-teal-600" aria-hidden />
          NextStep<span className="text-teal-600">.ai</span>
        </Link>

        {status === "loading" ? (
          <div className="h-8 w-24 animate-pulse rounded-md bg-slate-100" aria-hidden />
        ) : session?.user ? (
          <div className="relative" ref={menuRef}>
            <Button
              variant="ghost"
              size="sm"
              aria-haspopup="menu"
              aria-expanded={open}
              onClick={() => setOpen((v) => !v)}
            >
              <UserIcon className="h-4 w-4" aria-hidden />
              <span className="max-w-[10rem] truncate">{session.user.name ?? session.user.email}</span>
              <ChevronDown className="h-4 w-4 opacity-60" aria-hidden />
            </Button>
            {open ? (
              <div
                role="menu"
                className="absolute right-0 mt-2 w-48 overflow-hidden rounded-md border border-slate-200 bg-white py-1 shadow-lg"
              >
                <Link
                  role="menuitem"
                  href="/applications"
                  className="block px-3 py-2 text-sm hover:bg-slate-50"
                  onClick={() => setOpen(false)}
                >
                  My applications
                </Link>
                <Link
                  role="menuitem"
                  href="/saved"
                  className="block px-3 py-2 text-sm hover:bg-slate-50"
                  onClick={() => setOpen(false)}
                >
                  Saved jobs
                </Link>
                <Link
                  role="menuitem"
                  href="/onboarding"
                  className="block px-3 py-2 text-sm hover:bg-slate-50"
                  onClick={() => setOpen(false)}
                >
                  Profile
                </Link>
                <button
                  role="menuitem"
                  type="button"
                  className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-red-700 hover:bg-red-50"
                  onClick={() => {
                    clearTokenCache();
                    void signOut({ callbackUrl: "/jobs" });
                  }}
                >
                  <LogOut className="h-4 w-4" aria-hidden />
                  Sign out
                </button>
              </div>
            ) : null}
          </div>
        ) : (
          <Link
            href="/login"
            className="inline-flex h-8 items-center rounded-md border border-slate-300 bg-white px-3 text-xs font-semibold text-slate-900 hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
          >
            Sign in
          </Link>
        )}
      </div>
    </header>
  );
}
