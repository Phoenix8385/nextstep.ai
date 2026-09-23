import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useRefreshOnFocus } from "@/hooks/use-refresh-on-focus";

function setVisibility(state: DocumentVisibilityState): void {
  Object.defineProperty(document, "visibilityState", { value: state, configurable: true });
}

beforeEach(() => {
  vi.useFakeTimers();
  setVisibility("visible");
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useRefreshOnFocus", () => {
  it("refreshes when the window regains focus", () => {
    const refresh = vi.fn();
    renderHook(() => useRefreshOnFocus(refresh));

    act(() => void window.dispatchEvent(new Event("focus")));

    expect(refresh).toHaveBeenCalledOnce();
  });

  it("refreshes when the tab becomes visible again", () => {
    const refresh = vi.fn();
    renderHook(() => useRefreshOnFocus(refresh));

    setVisibility("hidden");
    act(() => void document.dispatchEvent(new Event("visibilitychange")));
    expect(refresh).not.toHaveBeenCalled(); // leaving the tab must not fetch

    setVisibility("visible");
    act(() => void document.dispatchEvent(new Event("visibilitychange")));
    expect(refresh).toHaveBeenCalledOnce();
  });

  it("collapses the focus + visibilitychange burst into one call", () => {
    const refresh = vi.fn();
    renderHook(() => useRefreshOnFocus(refresh));

    act(() => {
      window.dispatchEvent(new Event("focus"));
      document.dispatchEvent(new Event("visibilitychange"));
    });

    expect(refresh).toHaveBeenCalledOnce();
  });

  it("allows another refresh once the interval has passed", () => {
    const refresh = vi.fn();
    renderHook(() => useRefreshOnFocus(refresh, { minIntervalMs: 1000 }));

    act(() => void window.dispatchEvent(new Event("focus")));
    vi.advanceTimersByTime(1500);
    act(() => void window.dispatchEvent(new Event("focus")));

    expect(refresh).toHaveBeenCalledTimes(2);
  });

  it("does nothing while disabled", () => {
    const refresh = vi.fn();
    renderHook(() => useRefreshOnFocus(refresh, { enabled: false }));

    act(() => void window.dispatchEvent(new Event("focus")));

    expect(refresh).not.toHaveBeenCalled();
  });

  it("calls the latest callback, not a stale closure", () => {
    const first = vi.fn();
    const second = vi.fn();
    const { rerender } = renderHook(({ fn }) => useRefreshOnFocus(fn), {
      initialProps: { fn: first },
    });

    rerender({ fn: second });
    act(() => void window.dispatchEvent(new Event("focus")));

    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledOnce();
  });

  it("removes its listeners on unmount", () => {
    const refresh = vi.fn();
    const { unmount } = renderHook(() => useRefreshOnFocus(refresh));

    unmount();
    act(() => void window.dispatchEvent(new Event("focus")));

    expect(refresh).not.toHaveBeenCalled();
  });
});
