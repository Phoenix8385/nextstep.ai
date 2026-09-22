/**
 * Typed fetch wrapper for the FastAPI backend.
 *
 * - Base URL from `NEXT_PUBLIC_API_URL`.
 * - Attaches `Authorization: Bearer <token>` from the NextAuth session on the
 *   client (`getSession()`); server code passes `token` explicitly.
 * - JSON in/out, `FormData` passed through untouched, `ApiError` on non-2xx.
 */

import { getSession } from "next-auth/react";

export const API_URL: string = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, detail: unknown, message?: string) {
    super(message ?? ApiError.describe(status, detail));
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }

  static describe(status: number, detail: unknown): string {
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      const first = detail[0] as { msg?: string; loc?: unknown[] } | undefined;
      if (first?.msg) return `${(first.loc ?? []).slice(1).join(".")}: ${first.msg}`.trim();
    }
    return `Request failed with status ${status}`;
  }

  get isUnauthorized(): boolean {
    return this.status === 401;
  }
}

export interface ApiRequestOptions extends Omit<RequestInit, "body"> {
  /** JSON-serialisable body, or `FormData` for uploads. */
  body?: unknown;
  /** Explicit bearer token (server components / tests). `null` disables auth. */
  token?: string | null;
  /** Query parameters; `undefined`/`null`/`""` values are omitted. */
  query?: Record<string, string | number | boolean | null | undefined>;
}

// A short memo so bursts of requests do not each round-trip to /api/auth/session.
let cachedToken: { value: string | undefined; until: number } | null = null;
const TOKEN_CACHE_MS = 15_000;

async function resolveToken(explicit: string | null | undefined): Promise<string | undefined> {
  if (explicit === null) return undefined;
  if (explicit) return explicit;
  if (typeof window === "undefined") return undefined; // server: caller must pass a token
  if (cachedToken && cachedToken.until > Date.now()) return cachedToken.value;
  const session = await getSession();
  const value =
    session?.accessToken && (!session.accessTokenExpires || session.accessTokenExpires > Date.now())
      ? session.accessToken
      : undefined;
  cachedToken = { value, until: Date.now() + TOKEN_CACHE_MS };
  return value;
}

/** Forget the memoised token (call after sign-in/sign-out). */
export function clearTokenCache(): void {
  cachedToken = null;
}

export function buildQuery(query: ApiRequestOptions["query"]): string {
  if (!query) return "";
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") continue;
    params.set(key, String(value));
  }
  const encoded = params.toString();
  return encoded ? `?${encoded}` : "";
}

/**
 * Perform a request against the API and return the decoded JSON body.
 *
 * @throws {ApiError} for any non-2xx response, with the backend's `detail`.
 */
export async function apiFetch<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
  const { body, token, query, headers: initHeaders, ...init } = options;
  const headers = new Headers(initHeaders);
  headers.set("Accept", "application/json");

  const bearer = await resolveToken(token);
  if (bearer) headers.set("Authorization", `Bearer ${bearer}`);

  let payload: BodyInit | undefined;
  if (body instanceof FormData) {
    payload = body; // the browser sets the multipart boundary
  } else if (body !== undefined) {
    headers.set("Content-Type", "application/json");
    payload = JSON.stringify(body);
  }

  const response = await fetch(`${API_URL}${path}${buildQuery(query)}`, {
    ...init,
    headers,
    body: payload,
  });

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  const data: unknown = text ? safeJson(text) : undefined;
  if (!response.ok) {
    const detail =
      data && typeof data === "object" && "detail" in data ? (data as { detail: unknown }).detail : data;
    throw new ApiError(response.status, detail ?? response.statusText);
  }
  return data as T;
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

/** Convenience verbs. */
export const api = {
  get: <T>(path: string, options?: ApiRequestOptions) => apiFetch<T>(path, { ...options, method: "GET" }),
  post: <T>(path: string, body?: unknown, options?: ApiRequestOptions) =>
    apiFetch<T>(path, { ...options, method: "POST", body }),
  put: <T>(path: string, body?: unknown, options?: ApiRequestOptions) =>
    apiFetch<T>(path, { ...options, method: "PUT", body }),
  patch: <T>(path: string, body?: unknown, options?: ApiRequestOptions) =>
    apiFetch<T>(path, { ...options, method: "PATCH", body }),
  delete: <T = void>(path: string, options?: ApiRequestOptions) =>
    apiFetch<T>(path, { ...options, method: "DELETE" }),
};
