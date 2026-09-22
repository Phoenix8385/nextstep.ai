"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { signIn } from "next-auth/react";
import { Suspense, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { API_URL, ApiError, clearTokenCache } from "@/lib/api-client";

type Mode = "signin" | "signup";

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const callbackUrl = params.get("callbackUrl") ?? "/jobs";

  const [mode, setMode] = useState<Mode>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "signup") {
        const response = await fetch(`${API_URL}/auth/signup`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, password, full_name: fullName }),
        });
        if (!response.ok) {
          const body = (await response.json().catch(() => ({}))) as { detail?: unknown };
          throw new ApiError(response.status, body.detail ?? "Could not create the account");
        }
      }
      const result = await signIn("credentials", { email, password, redirect: false });
      if (!result || result.error) {
        setError("Invalid email or password");
        return;
      }
      clearTokenCache();
      router.push(callbackUrl);
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto mt-10 w-full max-w-sm rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
      <h1 className="text-xl font-bold">{mode === "signin" ? "Sign in" : "Create your account"}</h1>
      <p className="mt-1 text-sm text-slate-600">
        {mode === "signin" ? "Welcome back." : "Save jobs, analyze your resume, and track applications."}
      </p>

      <form onSubmit={onSubmit} className="mt-6 space-y-4" noValidate>
        {mode === "signup" ? (
          <label className="block text-sm">
            <span className="font-medium">Full name</span>
            <input
              required
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              autoComplete="name"
              className="mt-1 h-10 w-full rounded-md border border-slate-300 px-3 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
            />
          </label>
        ) : null}
        <label className="block text-sm">
          <span className="font-medium">Email</span>
          <input
            required
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="email"
            className="mt-1 h-10 w-full rounded-md border border-slate-300 px-3 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
          />
        </label>
        <label className="block text-sm">
          <span className="font-medium">Password</span>
          <input
            required
            type="password"
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete={mode === "signin" ? "current-password" : "new-password"}
            className="mt-1 h-10 w-full rounded-md border border-slate-300 px-3 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-500"
          />
        </label>

        {error ? (
          <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </p>
        ) : null}

        <Button type="submit" className="w-full" disabled={busy}>
          {busy ? "Please wait…" : mode === "signin" ? "Sign in" : "Create account"}
        </Button>
      </form>

      <button
        type="button"
        className="mt-4 w-full text-center text-sm text-teal-700 hover:underline"
        onClick={() => {
          setMode((m) => (m === "signin" ? "signup" : "signin"));
          setError(null);
        }}
      >
        {mode === "signin" ? "New here? Create an account" : "Already have an account? Sign in"}
      </button>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}
