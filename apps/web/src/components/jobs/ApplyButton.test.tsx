import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() } };
});
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }), usePathname: () => "/jobs/job-1" }));

const sessionStatus = { value: "authenticated" as "authenticated" | "unauthenticated" };
vi.mock("next-auth/react", () => ({ useSession: () => ({ status: sessionStatus.value, data: null }) }));

import { ApplyButton } from "@/components/jobs/ApplyButton";
import { Toaster } from "@/components/ui/toaster";
import { useToastStore } from "@/hooks/use-toast";
import { api, ApiError } from "@/lib/api-client";

const JOB = {
  id: "job-1",
  source_url: "https://boards.greenhouse.io/acme/jobs/1",
  title: "Backend Engineer",
  company_name: "Acme",
};

const TOAST_COPY = /don't forget to mark this as applied once you've submitted it/i;

function renderButton(props: Partial<Parameters<typeof ApplyButton>[0]> = {}) {
  return render(
    <>
      <ApplyButton job={JOB} {...props} />
      <Toaster />
    </>,
  );
}

beforeEach(() => {
  vi.mocked(api.post).mockReset().mockResolvedValue({});
  push.mockReset();
  sessionStatus.value = "authenticated";
  useToastStore.setState({ toasts: [] });
  vi.stubGlobal("open", vi.fn());
});

describe("Apply Now", () => {
  it("opens the posting in a new tab and shows the reminder toast with an inline action", async () => {
    const user = userEvent.setup();
    renderButton();

    await user.click(screen.getByRole("button", { name: /apply now/i }));

    expect(window.open).toHaveBeenCalledWith(JOB.source_url, "_blank", "noopener,noreferrer");

    const toast = await screen.findByText(TOAST_COPY);
    expect(toast).toBeInTheDocument();
    expect(screen.getByText(/acme/i)).toBeInTheDocument();
    // The toast carries its own inline action, and the button itself also flips over.
    const actions = screen.getAllByRole("button", { name: /mark as applied/i });
    expect(actions.length).toBeGreaterThanOrEqual(2);
  });

  it("does not record the application until the user confirms", async () => {
    const user = userEvent.setup();
    renderButton();

    await user.click(screen.getByRole("button", { name: /apply now/i }));
    await screen.findByText(TOAST_COPY);

    expect(api.post).not.toHaveBeenCalled(); // opening the tab is not applying
  });

  it("the toast's inline Mark as Applied records the application", async () => {
    const user = userEvent.setup();
    renderButton({ resumeVersionId: "version-3" });

    await user.click(screen.getByRole("button", { name: /apply now/i }));
    const [inlineAction] = await screen.findAllByRole("button", { name: /mark as applied/i });
    await user.click(inlineAction);

    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith("/applications", {
        job_id: "job-1",
        resume_version_id: "version-3",
        status: "applied",
      }),
    );
    expect(await screen.findByRole("button", { name: /^applied$/i })).toBeDisabled();
    expect(await screen.findByText(/marked as applied/i)).toBeInTheDocument();
  });

  it("the in-place Mark as Applied button records it too and calls onApplied", async () => {
    const user = userEvent.setup();
    const onApplied = vi.fn();
    renderButton({ onApplied });

    await user.click(screen.getByRole("button", { name: /apply now/i }));
    const buttons = await screen.findAllByRole("button", { name: /mark as applied/i });
    await user.click(buttons[buttons.length - 1]); // the button that replaced "Apply Now"

    await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
    expect(onApplied).toHaveBeenCalledOnce();
  });

  it("stays on Mark as Applied and explains when the API fails", async () => {
    const user = userEvent.setup();
    vi.mocked(api.post).mockRejectedValueOnce(new ApiError(500, "Database unavailable"));
    renderButton();

    await user.click(screen.getByRole("button", { name: /apply now/i }));
    const [inlineAction] = await screen.findAllByRole("button", { name: /mark as applied/i });
    await user.click(inlineAction);

    expect(await screen.findByText(/could not record the application/i)).toBeInTheDocument();
    expect(await screen.findByText(/database unavailable/i)).toBeInTheDocument();
    // Still recoverable: the button has not claimed success.
    expect(screen.queryByRole("button", { name: /^applied$/i })).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /mark as applied/i }).length).toBeGreaterThan(0);
  });

  it("sends a signed-out user to the login page instead of recording anything", async () => {
    const user = userEvent.setup();
    sessionStatus.value = "unauthenticated";
    renderButton();

    await user.click(screen.getByRole("button", { name: /apply now/i }));
    const [inlineAction] = await screen.findAllByRole("button", { name: /mark as applied/i });
    await user.click(inlineAction);

    expect(push).toHaveBeenCalledWith("/login?callbackUrl=%2Fjobs%2Fjob-1");
    expect(api.post).not.toHaveBeenCalled();
  });
});
