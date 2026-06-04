import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import {
  ActorFilter,
  JobsList,
  ProductMeta,
  StatusBadge,
  UserMenu,
  buildJobQuery,
  formatRuntimeUsageSeconds,
  groupSessionEvents,
  groupTranscriptEntries,
  isRetryableStatus,
  metricsSummaryPath,
  runtimeBucketLabel,
  selectedJobIdFromPath,
  shouldRefreshJobForSessionEvent,
} from "./main";

describe("dashboard routing and API query helpers", () => {
  it("builds trimmed job queries and preserves the requested limit", () => {
    expect(
      buildJobQuery(
        {
          status: " pending ",
          repo: " pilipilisbot/github-agent-bridge ",
          thread: "",
          action: " open_issue ",
          intent: " work_allowed ",
          actor: " ecarreras ",
        },
        24,
      ),
    ).toBe("/api/jobs?status=pending&repo=pilipilisbot%2Fgithub-agent-bridge&action=open_issue&intent=work_allowed&actor=ecarreras&limit=24");
  });

  it("recognizes only canonical job detail routes", () => {
    expect(selectedJobIdFromPath("/jobs/45")).toBe(45);
    expect(selectedJobIdFromPath("/jobs/45/")).toBe(45);
    expect(selectedJobIdFromPath("/jobs/not-a-number")).toBeNull();
    expect(selectedJobIdFromPath("/jobs/45/activity")).toBeNull();
  });

  it("refreshes job data only for session events that can change job state", () => {
    expect(shouldRefreshJobForSessionEvent("claimed")).toBe(true);
    expect(shouldRefreshJobForSessionEvent("dispatch_finished")).toBe(true);
    expect(shouldRefreshJobForSessionEvent("done")).toBe(true);
    expect(shouldRefreshJobForSessionEvent("openclaw_stdout")).toBe(false);
    expect(shouldRefreshJobForSessionEvent("openclaw_stderr")).toBe(false);
  });

  it("limits retry actions to manually recoverable job states", () => {
    expect(isRetryableStatus("blocked")).toBe(true);
    expect(isRetryableStatus("denied")).toBe(true);
    expect(isRetryableStatus("waiting_approval")).toBe(true);
    expect(isRetryableStatus("pending")).toBe(false);
    expect(isRetryableStatus("running")).toBe(false);
    expect(isRetryableStatus("done")).toBe(false);
  });

  it("requests metrics using the browser timezone and labels runtime buckets", () => {
    expect(metricsSummaryPath("America/New_York")).toBe("/api/metrics/summary?timezone=America%2FNew_York");
    expect(runtimeBucketLabel("2026-06-02", "day")).toMatch(/Jun|2/);
    expect(runtimeBucketLabel("2026-06", "month")).toMatch(/Jun|2026/);
  });

  it("formats runtime usage as human-readable hours and minutes", () => {
    expect(formatRuntimeUsageSeconds(30)).toBe("30s");
    expect(formatRuntimeUsageSeconds(1800)).toBe("30m");
    expect(formatRuntimeUsageSeconds(5400)).toBe("1h 30m");
    expect(formatRuntimeUsageSeconds(7200)).toBe("2h");
  });
});

describe("status badges", () => {
  it("pulses pending and running jobs, but leaves waiting approval static", () => {
    const { rerender } = render(<StatusBadge status="pending" />);
    expect(screen.getByText("pending").querySelector("span")).toHaveClass("animate-live-pulse");

    rerender(<StatusBadge status="running" />);
    expect(screen.getByText("running").querySelector("span")).toHaveClass("animate-live-pulse");

    rerender(<StatusBadge status="waiting_approval" />);
    expect(screen.getByText("waiting_approval").querySelector("span")).not.toHaveClass("animate-live-pulse");
  });

  it("keeps the jobs table header above animated status dots while scrolling", () => {
    render(
      <JobsList
        jobs={[
          {
            id: 58,
            work_key: "pilipilisbot/github-agent-bridge#58",
            repo: "pilipilisbot/github-agent-bridge",
            thread: 58,
            status: "pending",
            action: "open_issue",
            decision: "allowed",
            intent: "work_allowed",
            subject: "El dot del badge queda per sobre del header de la taula",
            trigger_actor: "ecarreras",
            trigger_actor_avatar_url: null,
            attempts: 1,
            coalesced_count: 1,
            last_error: null,
            locked_by: null,
            created_at: "2026-05-31T19:11:06Z",
            updated_at: "2026-05-31T19:11:06Z",
            started_at: null,
            finished_at: null,
            queue_wait_seconds: null,
            runtime_seconds: null,
            github_urls: [],
          },
        ]}
        loading={false}
        now={Date.parse("2026-05-31T19:12:00Z")}
        onViewJob={() => undefined}
      />,
    );

    expect(screen.getByRole("columnheader", { name: "Status" }).parentElement).toHaveClass("sticky", "top-0", "z-10");
  });
});

describe("product metadata", () => {
  it("shows the bridge version and upstream repository link", () => {
    render(<ProductMeta about={{ service: "github-agent-bridge-dashboard", version: "0.18.7", repository_url: "https://github.com/pilipilisbot/github-agent-bridge" }} />);

    expect(screen.getByText("Operational dashboard")).toBeInTheDocument();
    expect(screen.getByText("v0.18.7")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /github/i })).toHaveAttribute("href", "https://github.com/pilipilisbot/github-agent-bridge");
  });
});

describe("user menu", () => {
  it("shows admin and read-only modes beside the signed-in user", () => {
    const { rerender } = render(<UserMenu user={{ login: "alice", avatar_url: "", html_url: "https://github.com/alice", is_admin: true }} loading={false} />);
    expect(screen.getByText("Signed in · admin")).toBeInTheDocument();

    rerender(<UserMenu user={{ login: "bob", avatar_url: "", html_url: "https://github.com/bob", is_admin: false }} loading={false} />);
    expect(screen.getByText("Signed in · read-only")).toBeInTheDocument();
  });
});

describe("actor filter", () => {
  it("filters actors, selects a suggestion, and clears the selection", async () => {
    const user = userEvent.setup();
    let value = "";
    const options = [
      { login: "ecarreras", avatar_url: "https://example.com/ecarreras.png", job_count: 7, last_seen: "2026-05-25T12:00:00Z" },
      { login: "octocat", avatar_url: null, job_count: 2, last_seen: null },
    ];
    const onChange = (actor: string) => {
      value = actor;
      rerender(<ActorFilter value={value} options={options} onChange={onChange} />);
    };
    const { rerender } = render(<ActorFilter value={value} options={options} onChange={onChange} />);

    await user.type(screen.getByPlaceholderText("@login"), "eca");
    expect(screen.getByText("@ecarreras")).toBeInTheDocument();
    expect(screen.queryByText("@octocat")).not.toBeInTheDocument();

    await user.click(screen.getByText("@ecarreras"));
    expect(screen.getByPlaceholderText("@login")).toHaveValue("ecarreras");

    fireEvent.click(screen.getByLabelText("Clear actor filter"));
    expect(screen.getByPlaceholderText("@login")).toHaveValue("");
  });
});

describe("log grouping", () => {
  it("collapses consecutive OpenClaw CLI events while preserving boundaries", () => {
    const grouped = groupSessionEvents([
      { id: 1, ts: "2026-05-25T12:00:00Z", job_id: 45, work_key: "repo#45", session_id: "s1", event_type: "openclaw_stdout", summary: "stdout", detail: "first line" },
      { id: 2, ts: "2026-05-25T12:00:01Z", job_id: 45, work_key: "repo#45", session_id: "s1", event_type: "openclaw_stdout", summary: "stdout", detail: "second line" },
      { id: 3, ts: "2026-05-25T12:00:02Z", job_id: 45, work_key: "repo#45", session_id: "s1", event_type: "agent_message", summary: "done", detail: null },
    ]);

    expect(grouped).toHaveLength(2);
    expect(grouped[0]).toMatchObject({ count: 2, summary: "stdout (2): first line" });
    expect(grouped[0].detail).toBe("first line\nsecond line");
    expect(grouped[1]).toMatchObject({ count: 1, summary: "done" });
  });

  it("collapses consecutive transcript CLI entries", () => {
    const grouped = groupTranscriptEntries([
      { timestamp: "2026-05-25T12:00:00Z", role: "assistant", kind: "openclaw_stderr", title: "stderr", text: "warning" },
      { timestamp: "2026-05-25T12:00:01Z", role: "assistant", kind: "openclaw_stderr", title: "stderr", text: "details" },
      { timestamp: "2026-05-25T12:00:02Z", role: "assistant", kind: "message", title: "message", text: "finished" },
    ]);

    expect(grouped).toHaveLength(2);
    expect(grouped[0]).toMatchObject({ count: 2, summary: "assistant · openclaw_stderr (2): warning" });
    expect(grouped[0].text).toBe("warning\ndetails");
  });
});
