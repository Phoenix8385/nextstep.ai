import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next-auth/react", () => ({ getSession: vi.fn() }));

import { getSession } from "next-auth/react";

import { api, ApiError, apiFetch, buildQuery, clearTokenCache } from "@/lib/api-client";

const fetchMock = vi.fn();

function respond(status: number, body: unknown, ok = status < 400): void {
  fetchMock.mockResolvedValueOnce({
    ok,
    status,
    statusText: "status",
    text: async () => (body === undefined ? "" : JSON.stringify(body)),
  });
}

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  clearTokenCache();
  vi.mocked(getSession).mockResolvedValue({
    accessToken: "tok-123",
    accessTokenExpires: Date.now() + 60_000,
    expires: "",
    user: { id: "u1" },
  });
});

afterEach(() => {
  fetchMock.mockReset();
  vi.unstubAllGlobals();
});

describe("buildQuery", () => {
  it("omits empty values", () => {
    expect(buildQuery({ role: "eng", company: "", page: 2, x: undefined, y: null })).toBe(
      "?role=eng&page=2",
    );
    expect(buildQuery(undefined)).toBe("");
  });
});

describe("apiFetch", () => {
  it("attaches the session bearer token and JSON headers", async () => {
    respond(200, { ok: true });
    const result = await api.post<{ ok: boolean }>("/things", { a: 1 });
    expect(result).toEqual({ ok: true });

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/things");
    const headers = init.headers as Headers;
    expect(headers.get("Authorization")).toBe("Bearer tok-123");
    expect(headers.get("Content-Type")).toBe("application/json");
    expect(init.body).toBe(JSON.stringify({ a: 1 }));
  });

  it("skips auth when token is null and passes FormData through", async () => {
    respond(201, { id: "r1" });
    const form = new FormData();
    await apiFetch("/resumes", { method: "POST", body: form, token: null });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = init.headers as Headers;
    expect(headers.has("Authorization")).toBe(false);
    expect(headers.has("Content-Type")).toBe(false);
    expect(init.body).toBe(form);
  });

  it("throws ApiError with the backend detail", async () => {
    respond(401, { detail: "Not authenticated" });
    await expect(api.get("/saved-jobs")).rejects.toMatchObject({
      name: "ApiError",
      status: 401,
      message: "Not authenticated",
      isUnauthorized: true,
    });

    respond(422, { detail: [{ loc: ["body", "cgpa"], msg: "Input should be <= 9.99" }] });
    await expect(api.put("/profile", { cgpa: "10" })).rejects.toBeInstanceOf(ApiError);
  });

  it("memoises the session lookup briefly", async () => {
    respond(200, []);
    respond(200, []);
    await api.get("/a");
    await api.get("/b");
    expect(vi.mocked(getSession)).toHaveBeenCalledTimes(1);
  });

  it("returns undefined on 204", async () => {
    respond(204, undefined);
    await expect(api.delete("/jobs/1/save")).resolves.toBeUndefined();
  });
});
