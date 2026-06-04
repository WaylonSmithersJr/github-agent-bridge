import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import {
  ActorFilter,
  JobsList,
  KnowledgePage,
  KnowledgeProposals,
  ProductMeta,
  StatusBadge,
  UserMenu,
  buildJobQuery,
  buildKnowledgeQuery,
  formatRuntimeUsageSeconds,
  groupSessionEvents,
  groupTranscriptEntries,
  isKnowledgePath,
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

  it("builds knowledge queries and recognizes the knowledge route", () => {
    expect(buildKnowledgeQuery(" pilipilisbot/github-agent-bridge ", " proposed ", 25)).toBe("/api/knowledge?repo=pilipilisbot%2Fgithub-agent-bridge&status=proposed&limit=25");
    expect(isKnowledgePath("/knowledge")).toBe(true);
    expect(isKnowledgePath("/knowledge/")).toBe(true);
    expect(isKnowledgePath("/knowledge/extra")).toBe(false);
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

  it("lets admins retry recoverable jobs from the jobs list without opening the detail page", async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn().mockResolvedValue(undefined);
    const onViewJob = vi.fn();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);

    render(
      <JobsList
        jobs={[
          {
            id: 58,
            work_key: "pilipilisbot/github-agent-bridge#58",
            repo: "pilipilisbot/github-agent-bridge",
            thread: 58,
            status: "blocked",
            action: "reply_comment",
            decision: "allowed",
            intent: "work_allowed",
            subject: "Needs a guarded retry from the list",
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
        onViewJob={onViewJob}
        onRetry={onRetry}
        user={{ login: "admin", avatar_url: "", html_url: "https://github.com/admin", is_admin: true }}
      />,
    );

    await user.click(screen.getAllByRole("button", { name: "Retry job #58" })[0]);

    expect(confirm).toHaveBeenCalledWith("Retry job #58?");
    expect(onRetry).toHaveBeenCalledWith(58);
    expect(onViewJob).not.toHaveBeenCalled();
    confirm.mockRestore();
  });

  it("lets admins dismiss recoverable jobs from the jobs list without opening the detail page", async () => {
    const user = userEvent.setup();
    const onDismiss = vi.fn().mockResolvedValue(undefined);
    const onViewJob = vi.fn();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);

    render(
      <JobsList
        jobs={[
          {
            id: 58,
            work_key: "pilipilisbot/github-agent-bridge#58",
            repo: "pilipilisbot/github-agent-bridge",
            thread: 58,
            status: "blocked",
            action: "reply_comment",
            decision: "allowed",
            intent: "work_allowed",
            subject: "Needs an acknowledgement from the list",
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
        onViewJob={onViewJob}
        onDismiss={onDismiss}
        user={{ login: "admin", avatar_url: "", html_url: "https://github.com/admin", is_admin: true }}
      />,
    );

    await user.click(screen.getAllByRole("button", { name: "Dismiss job #58" })[0]);

    expect(confirm).toHaveBeenCalledWith("Dismiss job #58?");
    expect(onDismiss).toHaveBeenCalledWith(58);
    expect(onViewJob).not.toHaveBeenCalled();
    confirm.mockRestore();
  });

  it("hides list retry actions from read-only users and non-retryable jobs", () => {
    render(
      <JobsList
        jobs={[
          {
            id: 58,
            work_key: "pilipilisbot/github-agent-bridge#58",
            repo: "pilipilisbot/github-agent-bridge",
            thread: 58,
            status: "pending",
            action: "reply_comment",
            decision: "allowed",
            intent: "work_allowed",
            subject: "Pending jobs are not manually retried",
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
        onRetry={vi.fn()}
        onDismiss={vi.fn()}
        user={{ login: "reader", avatar_url: "", html_url: "https://github.com/reader", is_admin: false }}
      />,
    );

    expect(screen.queryByRole("button", { name: "Retry job #58" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Dismiss job #58" })).not.toBeInTheDocument();
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

describe("knowledge proposals", () => {
  it("keeps knowledge records separated behind tabs", async () => {
    const user = userEvent.setup();
    render(
      <KnowledgePage
        data={{
          repositories: ["pilipilisbot/github-agent-bridge"],
          summary: { proposed: 1, approved: 0, rules: 1, events: 1 },
          proposals: [
            {
              id: "feedback-proposal-1",
              event_id: "event-1",
              created_at: "2026-06-04T10:00:00Z",
              updated_at: "2026-06-04T10:01:00Z",
              status: "proposed",
              scope: "repo:pilipilisbot/github-agent-bridge",
              type: "operating_rule",
              confidence: 0.72,
              rule: "Keep knowledge moderation auditable.",
              reason: "A reusable process correction.",
              model: "gpt-test",
              error: null,
            },
          ],
          rules: [
            {
              id: "rule-1",
              scope: "repo:pilipilisbot/github-agent-bridge",
              type: "style_preference",
              rule: "Keep rule rows compact.",
              confidence: 0.82,
              observations: 2,
              source_events: ["event-1"],
              created_at: "2026-06-04T10:00:00Z",
              last_seen: "2026-06-04T10:01:00Z",
              source_event_details: [
                {
                  id: "event-1",
                  occurred_at: "2026-06-04T10:00:00Z",
                  captured_at: "2026-06-04T10:01:00Z",
                  source: "github",
                  scope: "repo:pilipilisbot/github-agent-bridge",
                  actor: "ecarreras",
                  trigger_actor: "ecarreras",
                  trigger_actor_avatar_url: "https://avatars.githubusercontent.com/u/294235?v=4",
                  github_urls: ["https://github.com/pilipilisbot/github-agent-bridge/issues/73#issuecomment-1"],
                  source_url: "https://github.com/pilipilisbot/github-agent-bridge/issues/73#issuecomment-1",
                  source_job_id: 510,
                  source_table: "job",
                  github_context: { urls: ["https://github.com/pilipilisbot/github-agent-bridge/issues/73#issuecomment-1"] },
                  comment: "Prefer tabs for knowledge.",
                  context: { issue: 73 },
                  classification: "style_preference",
                  confidence: 0.84,
                  memorable: true,
                },
              ],
            },
          ],
          events: [
            {
              id: "event-1",
              occurred_at: "2026-06-04T10:00:00Z",
              captured_at: "2026-06-04T10:01:00Z",
              source: "github",
              scope: "repo:pilipilisbot/github-agent-bridge",
              actor: "ecarreras",
              trigger_actor: "ecarreras",
              trigger_actor_avatar_url: "https://avatars.githubusercontent.com/u/294235?v=4",
              github_urls: ["https://github.com/pilipilisbot/github-agent-bridge/issues/73#issuecomment-1"],
              source_url: "https://github.com/pilipilisbot/github-agent-bridge/issues/73#issuecomment-1",
              source_job_id: 510,
              source_table: "job",
              github_context: { urls: ["https://github.com/pilipilisbot/github-agent-bridge/issues/73#issuecomment-1"] },
              comment: "Prefer tabs for knowledge.",
              context: { issue: 73 },
              classification: "style_preference",
              confidence: 0.84,
              memorable: true,
            },
          ],
        }}
        loading={false}
        error={null}
        repo=""
        status="proposed"
        user={{ login: "admin", avatar_url: "", html_url: "https://github.com/admin", is_admin: true }}
        now={Date.parse("2026-06-04T10:02:00Z")}
        onRepoChange={vi.fn()}
        onStatusChange={vi.fn()}
        onApprove={vi.fn()}
        onReject={vi.fn()}
        onDeleteRule={vi.fn()}
        onRefresh={vi.fn()}
      />,
    );

    expect(screen.queryByRole("link", { name: /^Dashboard$/i })).not.toBeInTheDocument();
    expect(screen.getByText("Keep knowledge moderation auditable.")).toBeInTheDocument();
    expect(screen.queryByText("Keep rule rows compact.")).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: /rules \(1\)/i }));
    expect(screen.getByText("Keep rule rows compact.")).toBeInTheDocument();
    expect(screen.queryByText("Keep knowledge moderation auditable.")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Proposal status")).not.toBeInTheDocument();
    expect(screen.getByText("@ecarreras")).toBeInTheDocument();
    expect(screen.getByText("Job #510")).toBeInTheDocument();
    expect(screen.getByText("pilipilisbot/github-agent-bridge/issues/73#issuecomment-1")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: /events \(1\)/i }));
    expect(screen.getByText("Prefer tabs for knowledge.")).toBeInTheDocument();
    expect(screen.getByText("@ecarreras")).toBeInTheDocument();
    expect(screen.getByText("Job #510")).toBeInTheDocument();
    expect(screen.getByText("pilipilisbot/github-agent-bridge/issues/73#issuecomment-1")).toBeInTheDocument();
  });

  it("shows moderation actions only to admins for proposed rules", async () => {
    const user = userEvent.setup();
    const onApprove = vi.fn().mockResolvedValue(undefined);
    const onReject = vi.fn().mockResolvedValue(undefined);
    const proposals = [
      {
        id: "feedback-proposal-1",
        event_id: "event-1",
        created_at: "2026-06-04T10:00:00Z",
        updated_at: "2026-06-04T10:01:00Z",
        status: "proposed",
        scope: "repo:pilipilisbot/github-agent-bridge",
        type: "operating_rule",
        confidence: 0.72,
        rule: "Keep knowledge moderation auditable.",
        reason: "A reusable process correction.",
        model: "gpt-test",
        error: null,
      },
    ];

    const { rerender } = render(<KnowledgeProposals proposals={proposals} loading={false} isAdmin={false} now={Date.parse("2026-06-04T10:02:00Z")} onApprove={onApprove} onReject={onReject} />);
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();

    rerender(<KnowledgeProposals proposals={proposals} loading={false} isAdmin={true} now={Date.parse("2026-06-04T10:02:00Z")} onApprove={onApprove} onReject={onReject} />);
    await user.click(screen.getByRole("button", { name: "Approve" }));

    expect(onApprove).toHaveBeenCalledWith("feedback-proposal-1");
    expect(onReject).not.toHaveBeenCalled();
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
