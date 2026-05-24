import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, AlertTriangle, ArrowLeft, CheckCircle2, ChevronDown, Clock3, Cpu, ExternalLink, Link, RefreshCw, Search, ShieldCheck, TerminalSquare, UserCircle2 } from "lucide-react";
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";
import "./styles.css";

type StatusCounts = Record<string, number>;

type MetricsSummary = {
  db_exists: boolean;
  schema_ok?: boolean;
  status_counts: StatusCounts;
  by_repo: Record<string, number>;
  by_action: Record<string, number>;
  by_intent: Record<string, number>;
  by_created_day: Record<string, number>;
  runtime_seconds: Percentiles;
  queue_wait_seconds: Percentiles;
};

type Percentiles = {
  median: number | null;
  p90: number | null;
  p99: number | null;
};

type Job = {
  id: number;
  work_key: string;
  repo: string | null;
  thread: number | null;
  status: string;
  action: string;
  decision: string;
  intent: string;
  subject: string;
  attempts: number;
  coalesced_count: number;
  last_error: string | null;
  locked_by: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
  queue_wait_seconds: number | null;
  runtime_seconds: number | null;
  github_urls: string[];
  worklog?: WorklogEntry[];
};

type WorklogEntry = {
  id: number;
  ts: string;
  phase: string;
  summary: string;
  detail: string | null;
};

type ProcessSample = {
  pid: number;
  ppid: number;
  state: string;
  cmd: string;
  cpu_ticks: number;
  io_bytes: { read_bytes?: number; write_bytes?: number } | null;
  children?: ProcessSample[];
};

type ProcessesResponse = {
  running_jobs: Array<{
    id: number;
    work_key: string;
    work_intent: string;
    locked_by: string | null;
    age_seconds: number | null;
    idle_seconds: number | null;
  }>;
  executor: {
    service: string;
    pid: number | null;
    children: ProcessSample[];
  };
  alerts: string[];
  detail: string;
};

type SessionCorrelation = {
  id: string;
  source: string;
  transcript_available: boolean;
  transcript_exposure: string;
  job_id: number;
  work_key: string;
  status: string;
  detail: string;
};

type SessionEvent = {
  id: number;
  ts: string;
  job_id: number;
  work_key: string | null;
  session_id: string;
  event_type: string;
  summary: string;
  detail: string | null;
};

type TranscriptEntry = {
  timestamp: string | null;
  role: string;
  kind: string;
  title: string;
  text: string;
};

type SessionEventGroup = {
  id: string;
  badge: string;
  meta: string | null;
  summary: string;
  detail: string | null;
  eventType: string;
  count: number;
};

type TranscriptEntryGroup = {
  id: string;
  badge: string;
  meta: string | null;
  summary: string;
  text: string;
  kind: string;
  count: number;
};

type UserProfile = {
  login: string;
  avatar_url: string;
  html_url: string;
};

type JobFilters = {
  status: string;
  repo: string;
  thread: string;
  action: string;
  intent: string;
};

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
    },
  },
});

function cn(...values: Array<string | false | null | undefined>) {
  return twMerge(clsx(values));
}

async function api<T>(path: string): Promise<T> {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

function formatSeconds(value: number | null | undefined) {
  if (value === null || value === undefined) return "n/a";
  if (value < 60) return `${value}s`;
  const minutes = Math.floor(value / 60);
  if (minutes < 60) return `${minutes}m ${value % 60}s`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

const dateTimeFormatter = new Intl.DateTimeFormat(undefined, {
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  timeZoneName: "short",
});

const compactDateFormatter = new Intl.DateTimeFormat(undefined, {
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

function parseDate(value: string | null | undefined) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatDateTime(value: string | null | undefined) {
  const date = parseDate(value);
  return date ? dateTimeFormatter.format(date) : (value ?? "");
}

function compactDate(value: string | null | undefined) {
  const date = parseDate(value);
  return date ? compactDateFormatter.format(date) : (value ?? "");
}

function TimeText({ value, compact = false }: { value: string | null | undefined; compact?: boolean }) {
  const date = parseDate(value);
  if (!date) return <>{value ?? ""}</>;
  return (
    <time dateTime={date.toISOString()} title={`UTC: ${date.toISOString()}`}>
      {compact ? compactDate(value) : formatDateTime(value)}
    </time>
  );
}

function firstLogLine(value: string | null | undefined) {
  const line = (value ?? "").split(/\r?\n/).map((item) => item.trim()).find(Boolean);
  return line ?? "";
}

function compactLogSummary(label: string, text: string | null | undefined, count = 1) {
  const preview = firstLogLine(text);
  const countLabel = count > 1 ? ` (${count})` : "";
  return preview ? `${label}${countLabel}: ${preview}` : `${label}${countLabel}`;
}

function isCliOutputKind(kind: string) {
  return kind === "openclaw_stdout" || kind === "openclaw_stderr";
}

function joinLogText(items: Array<string | null | undefined>) {
  return items.map((item) => item?.trim()).filter(Boolean).join("\n");
}

function groupSessionEvents(events: SessionEvent[]) {
  const groups: SessionEventGroup[] = [];
  for (const event of events) {
    const previous = groups[groups.length - 1];
    if (previous && isCliOutputKind(event.event_type) && previous.eventType === event.event_type) {
      previous.count += 1;
      previous.meta = event.ts;
      previous.detail = joinLogText([previous.detail, event.detail]);
      previous.summary = compactLogSummary(event.summary, previous.detail, previous.count);
      continue;
    }
    groups.push({
      id: String(event.id),
      badge: event.event_type,
      meta: event.ts,
      summary: isCliOutputKind(event.event_type) ? compactLogSummary(event.summary, event.detail) : event.summary,
      detail: event.detail,
      eventType: event.event_type,
      count: 1,
    });
  }
  return groups;
}

function groupTranscriptEntries(entries: TranscriptEntry[]) {
  const groups: TranscriptEntryGroup[] = [];
  entries.forEach((entry, index) => {
    const previous = groups[groups.length - 1];
    if (previous && isCliOutputKind(entry.kind) && previous.kind === entry.kind) {
      previous.count += 1;
      previous.meta = entry.timestamp;
      previous.text = joinLogText([previous.text, entry.text]);
      previous.summary = compactLogSummary(`${entry.role} · ${entry.kind}`, previous.text, previous.count);
      return;
    }
    groups.push({
      id: `${entry.timestamp ?? "entry"}-${index}`,
      badge: entry.title,
      meta: entry.timestamp,
      summary: isCliOutputKind(entry.kind) ? compactLogSummary(`${entry.role} · ${entry.kind}`, entry.text) : `${entry.role} · ${entry.kind}`,
      text: entry.text,
      kind: entry.kind,
      count: 1,
    });
  });
  return groups;
}

function defaultLogOpen(kind: string, running: boolean, index: number, total: number) {
  if (kind === "openclaw_stdout") return false;
  return running || index >= total - 2;
}

function statusTone(status: string) {
  return {
    pending: "border-amber-300 bg-amber-50 text-amber-800",
    running: "border-blue-300 bg-blue-50 text-blue-700",
    blocked: "border-red-300 bg-red-50 text-red-700",
    denied: "border-red-300 bg-red-50 text-red-700",
    done: "border-emerald-300 bg-emerald-50 text-emerald-700",
    waiting_approval: "border-slate-300 bg-slate-50 text-slate-700",
  }[status] ?? "border-slate-300 bg-slate-50 text-slate-700";
}

function buildJobQuery(filters: JobFilters) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value.trim()) params.set(key, value.trim());
  }
  return `/api/jobs?${params.toString()}`;
}

function safeExternalUrl(value: string) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : "#";
  } catch {
    return "#";
  }
}

function jobPath(jobId: number) {
  return `/jobs/${jobId}`;
}

function parseSseData<T>(message: MessageEvent): T | null {
  try {
    return JSON.parse(message.data) as T;
  } catch {
    return null;
  }
}

function appendUniqueById<T extends { id: number }>(items: T[], item: T) {
  if (items.some((existing) => existing.id === item.id)) return items;
  return [...items, item];
}

function appendTranscriptEntry(items: TranscriptEntry[], item: TranscriptEntry) {
  const key = transcriptKey(item);
  if (items.some((existing) => transcriptKey(existing) === key)) return items;
  return [...items, item];
}

function transcriptKey(item: TranscriptEntry) {
  return `${item.timestamp ?? ""}:${item.role}:${item.kind}:${item.title}:${item.text}`;
}

function selectedJobIdFromPath(pathname = window.location.pathname) {
  const match = pathname.match(/^\/jobs\/(\d+)\/?$/);
  return match ? Number(match[1]) : null;
}

function App() {
  const queryClient = useQueryClient();
  const [filters, setFilters] = React.useState<JobFilters>({ status: "", repo: "", thread: "", action: "", intent: "" });
  const [pathname, setPathname] = React.useState(() => window.location.pathname);
  const jobRouteId = selectedJobIdFromPath(pathname);
  const isJobDetailRoute = jobRouteId !== null;
  const selectedJobId = jobRouteId;
  const metrics = useQuery({ queryKey: ["metrics"], queryFn: () => api<{ metrics: MetricsSummary }>("/api/metrics/summary"), enabled: !isJobDetailRoute });
  const me = useQuery({ queryKey: ["me"], queryFn: () => api<{ user: UserProfile }>("/api/me"), refetchInterval: false });
  const jobs = useQuery({ queryKey: ["jobs", filters], queryFn: () => api<{ jobs: Job[] }>(buildJobQuery(filters)), enabled: !isJobDetailRoute });
  const processes = useQuery({ queryKey: ["processes"], queryFn: () => api<ProcessesResponse>("/api/processes"), enabled: !isJobDetailRoute });
  const detail = useQuery({
    queryKey: ["job", selectedJobId],
    queryFn: () => api<{ job: Job }>(`/api/jobs/${selectedJobId}`),
    enabled: selectedJobId !== null,
  });
  const session = useQuery({
    queryKey: ["job-session", selectedJobId],
    queryFn: () => api<{ session: SessionCorrelation }>(`/api/jobs/${selectedJobId}/session`),
    enabled: selectedJobId !== null,
  });
  const sessionEvents = useQuery({
    queryKey: ["job-session-events", selectedJobId],
    queryFn: () => api<{ events: SessionEvent[] }>(`/api/jobs/${selectedJobId}/session/events`),
    enabled: selectedJobId !== null,
  });
  const transcript = useQuery({
    queryKey: ["job-session-transcript", selectedJobId],
    queryFn: () => api<{ entries: TranscriptEntry[] }>(`/api/jobs/${selectedJobId}/session/transcript`),
    enabled: selectedJobId !== null,
  });

  React.useEffect(() => {
    if (selectedJobId === null) return;
    const source = new EventSource(`/api/jobs/${selectedJobId}/session/stream`);
    source.addEventListener("session_event", (message) => {
      const event = parseSseData<SessionEvent>(message);
      if (!event) return;
      queryClient.setQueryData<{ events: SessionEvent[] }>(["job-session-events", selectedJobId], (current) => ({
        events: appendUniqueById(current?.events ?? [], event),
      }));
      queryClient.invalidateQueries({ queryKey: ["job", selectedJobId] });
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
    });
    source.addEventListener("transcript_entry", (message) => {
      const payload = parseSseData<{ job_id: number; entry: TranscriptEntry }>(message);
      if (!payload || payload.job_id !== selectedJobId) return;
      queryClient.setQueryData<{ entries: TranscriptEntry[] }>(["job-session-transcript", selectedJobId], (current) => ({
        entries: appendTranscriptEntry(current?.entries ?? [], payload.entry),
      }));
    });
    source.onerror = () => {
      source.close();
    };
    return () => source.close();
  }, [selectedJobId, queryClient]);

  React.useEffect(() => {
    const syncFromPath = () => {
      setPathname(window.location.pathname);
    };
    window.addEventListener("popstate", syncFromPath);
    return () => window.removeEventListener("popstate", syncFromPath);
  }, []);

  const viewJob = React.useCallback((jobId: number) => {
    window.history.pushState({}, "", jobPath(jobId));
    setPathname(window.location.pathname);
  }, []);

  const counts = metrics.data?.metrics.status_counts ?? {};
  const jobRows = jobs.data?.jobs ?? [];
  const selectedJob = selectedJobId ? (detail.data?.job ?? null) : null;
  const detailStatus = <JobDetailStatus selectedJobId={selectedJobId} selectedJob={selectedJob} loading={detail.isLoading} error={detail.error} session={session.data?.session} sessionEvents={sessionEvents.data?.events} transcript={transcript.data?.entries} />;

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="border-b border-slate-800 bg-slate-950 text-white">
        <div className="mx-auto flex w-full max-w-[1440px] flex-col gap-3 px-4 py-4 md:flex-row md:items-center md:justify-between md:px-6">
          <div>
            <h1 className="text-xl font-semibold">GitHub Agent Bridge</h1>
            <p className="text-sm text-slate-300">Read-only operational dashboard</p>
          </div>
          <UserMenu user={me.data?.user} loading={me.isLoading} />
        </div>
      </header>

      <main className="mx-auto grid w-full max-w-[1440px] gap-4 px-4 py-4 md:px-6 md:py-5">
        {jobRouteId !== null ? (
          <JobDetailPage
            jobId={jobRouteId}
            detail={detailStatus}
            onRefresh={() => {
              detail.refetch();
              session.refetch();
              sessionEvents.refetch();
              transcript.refetch();
            }}
          />
        ) : (
          <>
            {metrics.error ? <Banner tone="error" text={metrics.error.message} /> : null}
            <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-4" aria-label="Summary metrics">
              <Metric title="Pending" value={counts.pending ?? 0} icon={<Clock3 className="h-5 w-5" />} />
              <Metric title="Running" value={counts.running ?? 0} icon={<Activity className="h-5 w-5" />} />
              <Metric title="Blocked" value={counts.blocked ?? 0} icon={<AlertTriangle className="h-5 w-5" />} />
              <Metric title="Done" value={counts.done ?? 0} icon={<CheckCircle2 className="h-5 w-5" />} />
            </section>

            <section>
              <Panel title="Jobs" action={<RefreshButton onClick={() => jobs.refetch()} />}>
                <Filters filters={filters} onChange={setFilters} />
                {jobs.error ? <Banner tone="error" text={jobs.error.message} /> : null}
                <JobsList jobs={jobRows} loading={jobs.isLoading} onViewJob={viewJob} />
              </Panel>
            </section>

            <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
              <Panel title="Process activity" action={<RefreshButton onClick={() => processes.refetch()} />}>
                {processes.error ? <Banner tone="error" text={processes.error.message} /> : null}
                <ProcessActivity data={processes.data} loading={processes.isLoading} />
              </Panel>
              <Panel title="Runtime percentiles">
                <PercentileChart label="runtime" values={metrics.data?.metrics.runtime_seconds} />
              </Panel>
            </section>

            <section className="grid gap-4 xl:grid-cols-2">
              <Panel title="Jobs per day">
                <JobsPerDayChart values={metrics.data?.metrics.by_created_day} loading={metrics.isLoading} totalJobs={totalJobs(counts)} />
              </Panel>
              <Panel title="Queue wait percentiles">
                <PercentileChart label="queue wait" values={metrics.data?.metrics.queue_wait_seconds} />
              </Panel>
            </section>
          </>
        )}
      </main>
    </div>
  );
}

function JobDetailPage({ jobId, detail, onRefresh }: { jobId: number; detail: React.ReactNode; onRefresh: () => void }) {
  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <a className="inline-flex h-9 items-center gap-2 rounded-md border border-border px-3 text-sm font-semibold text-foreground hover:bg-slate-50" href="/">
          <ArrowLeft className="h-4 w-4" aria-hidden />
          Dashboard
        </a>
        <RefreshButton onClick={onRefresh} />
      </div>
      <Panel title={`Job #${jobId}`}>
        {detail}
      </Panel>
    </div>
  );
}

function JobDetailStatus({
  selectedJobId,
  selectedJob,
  loading,
  error,
  session,
  sessionEvents,
  transcript,
}: {
  selectedJobId: number | null;
  selectedJob: Job | null;
  loading: boolean;
  error: Error | null;
  session: SessionCorrelation | undefined;
  sessionEvents: SessionEvent[] | undefined;
  transcript: TranscriptEntry[] | undefined;
}) {
  if (selectedJob) return <JobDetail job={selectedJob} session={session} sessionEvents={sessionEvents} transcript={transcript} />;
  if (selectedJobId !== null && loading) return <EmptyState text="Loading selected job..." />;
  if (selectedJobId !== null && error) return <Banner tone="error" text={`Job #${selectedJobId}: ${error.message}`} />;
  return <EmptyState text="Select a job to inspect its timeline, worklog and GitHub links." />;
}

function UserMenu({ user, loading }: { user: UserProfile | undefined; loading: boolean }) {
  const login = user?.login ? `@${user.login}` : loading ? "Loading profile..." : "GitHub OAuth";
  const avatar = user?.avatar_url ? (
    <img className="h-10 w-10 rounded-full border border-slate-700 bg-slate-800" src={user.avatar_url} alt={user.login ? `${user.login} avatar` : ""} referrerPolicy="no-referrer" />
  ) : (
    <span className="inline-flex h-10 w-10 items-center justify-center rounded-full border border-slate-700 bg-slate-900">
      <UserCircle2 className="h-5 w-5" aria-hidden />
    </span>
  );
  const identity = user?.html_url ? (
    <a className="truncate font-semibold text-white hover:underline" href={safeExternalUrl(user.html_url)} rel="noreferrer" target="_blank">
      {login}
    </a>
  ) : (
    <div className="truncate font-semibold text-white">{login}</div>
  );
  return (
    <div className="flex max-w-full items-center gap-3 text-sm text-slate-300">
      <ShieldCheck className="h-4 w-4 shrink-0" aria-hidden />
      <div className="min-w-0 text-right">
        {identity}
        <div className="text-xs text-slate-400">Signed in · read-only</div>
      </div>
      {avatar}
    </div>
  );
}

function Panel({ title, action, children, className }: { title: string; action?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <section className={cn("rounded-lg border border-border bg-panel p-4 shadow-sm", className)}>
      <div className="mb-4 flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

function Metric({ title, value, icon }: { title: string; value: number; icon: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-border bg-panel p-4 shadow-sm">
      <div className="flex items-center justify-between text-muted">
        <span className="text-sm font-medium">{title}</span>
        {icon}
      </div>
      <strong className="mt-4 block text-3xl leading-none">{value}</strong>
    </div>
  );
}

function Filters({ filters, onChange }: { filters: JobFilters; onChange: (filters: JobFilters) => void }) {
  const [draft, setDraft] = React.useState(filters);
  return (
    <form
      className="mb-4 grid gap-3 md:grid-cols-3 xl:grid-cols-6"
      onSubmit={(event) => {
        event.preventDefault();
        onChange(draft);
      }}
    >
      <Field label="Status">
        <select className="control" value={draft.status} onChange={(event) => setDraft({ ...draft, status: event.target.value })}>
          <option value="">All</option>
          <option value="pending">pending</option>
          <option value="running">running</option>
          <option value="blocked">blocked</option>
          <option value="done">done</option>
          <option value="denied">denied</option>
          <option value="waiting_approval">waiting_approval</option>
        </select>
      </Field>
      <Field label="Repository">
        <input className="control" value={draft.repo} placeholder="owner/repo" onChange={(event) => setDraft({ ...draft, repo: event.target.value })} />
      </Field>
      <Field label="Thread">
        <input className="control" value={draft.thread} inputMode="numeric" placeholder="issue or PR" onChange={(event) => setDraft({ ...draft, thread: event.target.value })} />
      </Field>
      <Field label="Action">
        <input className="control" value={draft.action} placeholder="reply_comment" onChange={(event) => setDraft({ ...draft, action: event.target.value })} />
      </Field>
      <Field label="Intent">
        <select className="control" value={draft.intent} onChange={(event) => setDraft({ ...draft, intent: event.target.value })}>
          <option value="">All</option>
          <option value="review_only">review_only</option>
          <option value="work_allowed">work_allowed</option>
        </select>
      </Field>
      <button className="inline-flex h-9 items-center justify-center gap-2 rounded-md bg-primary px-3 text-sm font-semibold text-white" type="submit">
        <Search className="h-4 w-4" aria-hidden />
        Apply
      </button>
    </form>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="grid gap-1 text-xs font-semibold text-muted">
      {label}
      {children}
    </label>
  );
}

function JobsList({
  jobs,
  loading,
  onViewJob,
}: {
  jobs: Job[];
  loading: boolean;
  onViewJob: (id: number) => void;
}) {
  if (loading && jobs.length === 0) return <EmptyState text="Loading jobs..." />;
  if (jobs.length === 0) return <EmptyState text="No jobs match the current filters." />;
  return (
    <>
      <div className="grid gap-3 md:hidden">
        {jobs.map((job) => (
          <JobCard key={job.id} job={job} onViewJob={onViewJob} />
        ))}
      </div>
      <div className="hidden max-h-[640px] overflow-auto rounded-md border border-border md:block">
      <table className="min-w-full border-collapse text-sm">
        <thead>
          <tr className="sticky top-0 border-b border-border bg-panel text-left text-xs text-muted">
            <th className="px-2 py-2 font-semibold">ID</th>
            <th className="px-2 py-2 font-semibold">Status</th>
            <th className="px-2 py-2 font-semibold">Repo / thread</th>
            <th className="px-2 py-2 font-semibold">Action</th>
            <th className="px-2 py-2 font-semibold">Attempts</th>
            <th className="px-2 py-2 font-semibold">Queue wait</th>
            <th className="px-2 py-2 font-semibold">Runtime</th>
            <th className="px-2 py-2 font-semibold">Updated</th>
          </tr>
        </thead>
        <tbody>
          {jobs.map((job) => (
            <tr
              key={job.id}
              className="cursor-pointer border-b border-border hover:bg-slate-50"
              onClick={() => onViewJob(job.id)}
            >
              <td className="px-2 py-3 font-mono">#{job.id}</td>
              <td className="px-2 py-3">
                <StatusBadge status={job.status} />
              </td>
              <td className="px-2 py-3">
                <div className="font-mono">{job.repo ?? job.work_key}</div>
                <div className="text-xs text-muted">thread {job.thread ?? "n/a"}</div>
              </td>
              <td className="px-2 py-3">
                <div>{job.action}</div>
                <div className="text-xs text-muted">{job.intent}</div>
              </td>
              <td className="px-2 py-3">{job.attempts}</td>
              <td className="px-2 py-3">{formatSeconds(job.queue_wait_seconds)}</td>
              <td className="px-2 py-3">{formatSeconds(job.runtime_seconds)}</td>
              <td className="px-2 py-3 font-mono text-xs"><TimeText value={job.updated_at} compact /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
    </>
  );
}

function JobCard({
  job,
  onViewJob,
}: {
  job: Job;
  onViewJob: (id: number) => void;
}) {
  return (
    <article className="rounded-md border border-border bg-white">
      <button className="grid w-full gap-3 p-3 text-left hover:bg-slate-50" type="button" onClick={() => onViewJob(job.id)}>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="font-mono text-sm">#{job.id} {job.repo ?? job.work_key}</div>
            <div className="mt-1 truncate text-xs text-muted">thread {job.thread ?? "n/a"} · {job.action}</div>
          </div>
          <StatusBadge status={job.status} />
        </div>
        <div className="grid grid-cols-3 gap-2 text-xs">
          <MiniStat label="Wait" value={formatSeconds(job.queue_wait_seconds)} />
          <MiniStat label="Runtime" value={formatSeconds(job.runtime_seconds)} />
          <MiniStat label="Updated" value={compactDate(job.updated_at)} />
        </div>
      </button>
    </article>
  );
}

function JobDetail({ job, session, sessionEvents, transcript, compact = false }: { job: Job; session: SessionCorrelation | undefined; sessionEvents: SessionEvent[] | undefined; transcript: TranscriptEntry[] | undefined; compact?: boolean }) {
  const shareHref = jobPath(job.id);
  const eventRows = sessionEvents ?? [];
  const transcriptRows = transcript ?? [];
  const activityGroups = groupSessionEvents(eventRows);
  const transcriptGroups = groupTranscriptEntries(transcriptRows);
  return (
    <div className="grid gap-4">
      <div className="grid gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge status={job.status} />
          <a className="inline-flex h-7 items-center gap-1 rounded-md border border-border px-2 text-xs font-semibold text-foreground hover:bg-slate-50" href={shareHref}>
            <Link className="h-3.5 w-3.5" aria-hidden />
            Job #{job.id}
          </a>
        </div>
        <div className="font-mono text-sm">{job.work_key}</div>
        <p className="text-sm text-muted">{job.subject}</p>
      </div>
      <div className={cn("grid gap-3 text-sm", compact ? "grid-cols-1" : "grid-cols-3")}>
        <MiniStat label="Queue wait" value={formatSeconds(job.queue_wait_seconds)} />
        <MiniStat label="Runtime" value={formatSeconds(job.runtime_seconds)} />
        <MiniStat label="Coalesced" value={String(job.coalesced_count)} />
      </div>
      <div className={cn("grid gap-3 text-sm", compact ? "grid-cols-1" : "md:grid-cols-2 xl:grid-cols-4")}>
        <MiniStat label="Created" value={<TimeText value={job.created_at} />} />
        <MiniStat label="Started" value={job.started_at ? <TimeText value={job.started_at} /> : "n/a"} />
        <MiniStat label="Updated" value={<TimeText value={job.updated_at} />} />
        <MiniStat label="Finished" value={job.finished_at ? <TimeText value={job.finished_at} /> : "n/a"} />
      </div>
      <div>
        <h3 className="mb-2 text-sm font-semibold">Timeline</h3>
        <div className="grid gap-3">
          {(job.worklog ?? []).length > 0 ? (
            job.worklog?.map((entry) => (
              <div key={entry.id} className="border-l-2 border-primary pl-3">
                <div className="text-sm font-semibold">{entry.phase}</div>
                <div className="font-mono text-xs text-muted"><TimeText value={entry.ts} /></div>
                <div className="text-sm">{entry.summary}</div>
                {entry.detail ? <div className="mt-1 break-words font-mono text-xs text-muted">{entry.detail}</div> : null}
              </div>
            ))
          ) : (
            <EmptyState text="No worklog entries." />
          )}
        </div>
      </div>
      <div>
        <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold">
          <TerminalSquare className="h-4 w-4" aria-hidden />
          OpenClaw session
        </h3>
        {session ? (
          <div className="grid gap-3">
            <div className="grid gap-3 md:grid-cols-2">
              <MiniStat label="Session ID" value={session.id} />
              <MiniStat label="Source" value={session.source} />
            </div>
            <p className="text-xs text-muted">{session.detail}</p>
          </div>
        ) : (
          <EmptyState text="Session correlation is loading." />
        )}
      </div>
      <div>
        <h3 className="mb-2 text-sm font-semibold">Agent activity</h3>
        <div className="grid max-h-[460px] gap-2 overflow-auto pr-1">
          {activityGroups.length > 0 ? (
            activityGroups.map((event, index) => (
              <SessionEventRow key={event.id} event={event} defaultOpen={defaultLogOpen(event.eventType, job.status === "running", index, activityGroups.length)} />
            ))
          ) : (
            <EmptyState text={job.status === "running" ? "Waiting for live agent output..." : "No agent activity has been recorded for this session."} />
          )}
        </div>
      </div>
      <div>
        <h3 className="mb-2 text-sm font-semibold">Session transcript</h3>
        <div className="grid max-h-[620px] gap-2 overflow-auto pr-1">
          {transcriptGroups.length > 0 ? (
            transcriptGroups.map((entry, index) => (
              <TranscriptRow key={entry.id} entry={entry} defaultOpen={defaultLogOpen(entry.kind, job.status === "running", index, transcriptGroups.length)} />
            ))
          ) : (
            <EmptyState text={job.status === "running" ? "Waiting for live transcript entries..." : "No OpenClaw transcript entries are available for this session."} />
          )}
        </div>
      </div>
      <div>
        <h3 className="mb-2 text-sm font-semibold">GitHub links</h3>
        <ul className="grid gap-2 text-sm">
          {job.github_urls.length > 0 ? (
            job.github_urls.map((url) => (
              <li key={url}>
                <a className="break-all text-primary hover:underline" href={safeExternalUrl(url)} rel="noreferrer" target="_blank">
                  <ExternalLink className="mr-1 inline h-3.5 w-3.5 align-[-2px]" aria-hidden />
                  {url}
                </a>
              </li>
            ))
          ) : (
            <li className="text-muted">No links recorded.</li>
          )}
        </ul>
      </div>
    </div>
  );
}

function TranscriptRow({ entry, defaultOpen }: { entry: TranscriptEntryGroup; defaultOpen?: boolean }) {
  return (
    <CollapsibleLogSection
      badge={entry.badge}
      meta={<TimeText value={entry.meta} />}
      count={entry.count}
      summary={entry.summary}
      defaultOpen={defaultOpen}
    >
      <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded bg-slate-950 px-2 py-1.5 font-mono text-xs leading-relaxed text-slate-100">{entry.text}</pre>
    </CollapsibleLogSection>
  );
}

function SessionEventRow({ event, defaultOpen }: { event: SessionEventGroup; defaultOpen?: boolean }) {
  return (
    <CollapsibleLogSection badge={event.badge} meta={<TimeText value={event.meta} />} count={event.count} summary={event.summary} defaultOpen={defaultOpen}>
      {event.detail ? <pre className="max-h-56 overflow-auto whitespace-pre-wrap break-words rounded bg-slate-950 px-2 py-1.5 font-mono text-xs leading-relaxed text-slate-100">{event.detail}</pre> : null}
    </CollapsibleLogSection>
  );
}

function CollapsibleLogSection({
  badge,
  meta,
  count,
  summary,
  defaultOpen,
  children,
}: {
  badge: string;
  meta: React.ReactNode;
  count?: number;
  summary: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [isOpen, setIsOpen] = React.useState(Boolean(defaultOpen));
  return (
    <details className="group rounded border border-border bg-slate-50/60" open={isOpen} onToggle={(event) => setIsOpen(event.currentTarget.open)}>
      <summary className="grid cursor-pointer list-none gap-1 px-2 py-1.5 marker:hidden hover:bg-white">
        <div className="flex min-w-0 items-center justify-between gap-2">
          <div className="flex min-w-0 items-center gap-1.5">
            <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted transition-transform group-open:rotate-180" aria-hidden />
            <span className="truncate font-mono text-[11px] font-semibold text-muted">{badge}</span>
            {count && count > 1 ? <span className="rounded-sm border border-border px-1 font-mono text-[10px] text-muted">{count}</span> : null}
          </div>
          <span className="shrink-0 font-mono text-[11px] text-muted">{meta}</span>
        </div>
        <div className="min-w-0 truncate pl-5 text-xs text-foreground">{summary}</div>
      </summary>
      <div className="border-t border-border bg-white px-2 py-2">{children}</div>
    </details>
  );
}

function PercentileChart({ label, values }: { label: string; values: Percentiles | undefined }) {
  const data = [
    { name: "median", seconds: values?.median ?? 0 },
    { name: "p90", seconds: values?.p90 ?? 0 },
    { name: "p99", seconds: values?.p99 ?? 0 },
  ];
  return (
    <div className="h-56">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="name" />
          <YAxis tickFormatter={formatSeconds} />
          <Tooltip formatter={(value) => [formatSeconds(Number(value)), label]} />
          <Bar dataKey="seconds" fill="#0969da" radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function JobsPerDayChart({ values, loading, totalJobs }: { values: Record<string, number> | undefined; loading: boolean; totalJobs: number }) {
  const data = Object.entries(values ?? {}).map(([day, count]) => ({ day, count }));
  if (loading && data.length === 0) return <EmptyState text="Loading job history..." />;
  if (data.length === 0) return <EmptyState text={totalJobs > 0 ? "Job history has no valid creation dates." : "No job history available."} />;
  return (
    <div className="h-56">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="day" minTickGap={16} />
          <YAxis allowDecimals={false} />
          <Tooltip formatter={(value) => [Number(value), "jobs"]} />
          <Bar dataKey="count" fill="#16a34a" radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

function totalJobs(counts: StatusCounts) {
  return Object.values(counts).reduce((total, value) => total + value, 0);
}

function ProcessActivity({ data, loading }: { data: ProcessesResponse | undefined; loading: boolean }) {
  if (loading && !data) return <EmptyState text="Loading process activity..." />;
  if (!data) return <EmptyState text="No process snapshot available." />;
  const children = data.executor.children ?? [];
  const allProcesses = children.flatMap((process) => flattenProcessTree(process));
  const totalCpuTicks = allProcesses.reduce((total, process) => total + process.cpu_ticks, 0);
  const totalIoBytes = allProcesses.reduce((total, process) => total + totalIo(process), 0);
  const isActive = data.executor.service === "active";
  const chartData = allProcesses.slice(0, 8).map((process) => ({
    label: `pid ${process.pid}`,
    ticks: process.cpu_ticks,
  }));
  return (
    <div className="grid gap-4">
      <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className={cn("inline-flex h-6 items-center rounded-full border px-2 text-xs font-semibold", isActive ? "border-emerald-300 bg-emerald-50 text-emerald-700" : "border-slate-300 bg-white text-slate-600")}>
                {isActive ? "active" : "idle"}
              </span>
              <span className="font-mono text-xs text-muted">service {data.executor.service}</span>
            </div>
            <div className="mt-2 text-sm font-semibold text-foreground">
              {data.running_jobs.length > 0 ? `${data.running_jobs.length} running job${data.running_jobs.length === 1 ? "" : "s"}` : "No running jobs"}
            </div>
            <p className="mt-1 text-xs text-muted">{data.detail}</p>
          </div>
          <div className="grid min-w-[190px] grid-cols-3 gap-2 text-center text-xs">
            <ProcessKpi label="PID" value={data.executor.pid ? String(data.executor.pid) : "n/a"} />
            <ProcessKpi label="Children" value={String(allProcesses.length)} />
            <ProcessKpi label="CPU ticks" value={String(totalCpuTicks)} />
          </div>
        </div>
      </div>
      {data.alerts.length > 0 ? <Banner tone="error" text={data.alerts[0]} /> : null}
      <div className="grid gap-4 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <div className="min-w-0 rounded-md border border-border p-3">
          <div className="mb-3 flex items-center justify-between gap-3">
            <h3 className="flex items-center gap-2 text-sm font-semibold">
              <Cpu className="h-4 w-4" aria-hidden />
              CPU ticks
            </h3>
            <span className="font-mono text-xs text-muted">{formatBytes(totalIoBytes)} I/O</span>
          </div>
          {chartData.length > 0 ? (
            <div className="h-40">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="label" tick={false} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
                  <Tooltip formatter={(value) => [Number(value), "cpu ticks"]} />
                  <Line type="monotone" dataKey="ticks" stroke="#0f766e" strokeWidth={2} dot={{ r: 3 }} activeDot={{ r: 5 }} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <EmptyState text="No executor CPU samples available." />
          )}
        </div>
        <div className="min-w-0">
          <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold">
            <Cpu className="h-4 w-4" aria-hidden />
            Executor children
          </h3>
          {children.length > 0 ? (
            <div className="grid gap-2">
              {children.map((child) => (
                <ProcessRow key={child.pid} process={child} />
              ))}
            </div>
          ) : (
            <EmptyState text="No child process detected for the executor." />
          )}
        </div>
      </div>
    </div>
  );
}

function ProcessRow({ process }: { process: ProcessSample }) {
  const read = process.io_bytes?.read_bytes ?? 0;
  const written = process.io_bytes?.write_bytes ?? 0;
  return (
    <div className="rounded-md border border-border bg-white p-2.5">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-mono">pid {process.pid}</span>
        <span className="rounded-full border border-border px-2 text-xs text-muted">state {process.state}</span>
        <span className="rounded-full border border-border px-2 text-xs text-muted">cpu {process.cpu_ticks}</span>
        <span className="rounded-full border border-border px-2 text-xs text-muted">I/O {formatBytes(read + written)}</span>
      </div>
      <div className="mt-2 break-words font-mono text-xs text-muted">{process.cmd || "unknown command"}</div>
      {process.children && process.children.length > 0 ? (
        <div className="mt-3 border-l-2 border-border pl-3">
          {process.children.map((child) => (
            <ProcessRow key={child.pid} process={child} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function ProcessKpi({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border bg-white px-2 py-2">
      <div className="font-mono text-sm font-semibold text-foreground">{value}</div>
      <div className="mt-0.5 text-[11px] font-semibold uppercase text-muted">{label}</div>
    </div>
  );
}

function flattenProcessTree(process: ProcessSample): ProcessSample[] {
  return [process, ...(process.children ?? []).flatMap((child) => flattenProcessTree(child))];
}

function totalIo(process: ProcessSample) {
  return (process.io_bytes?.read_bytes ?? 0) + (process.io_bytes?.write_bytes ?? 0);
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MiB`;
}

function MiniStat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="min-w-0 rounded-md border border-border p-3">
      <div className="text-xs font-semibold text-muted">{label}</div>
      <div className="mt-1 break-words text-sm">{value}</div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  return <span className={cn("inline-flex min-h-6 items-center rounded-full border px-2 text-xs font-semibold", statusTone(status))}>{status}</span>;
}

function EmptyState({ text }: { text: string }) {
  return <div className="rounded-md border border-dashed border-border p-6 text-center text-sm text-muted">{text}</div>;
}

function Banner({ tone, text }: { tone: "error"; text: string }) {
  return <div className={cn("rounded-md border p-3 text-sm", tone === "error" && "border-red-300 bg-red-50 text-red-700")}>{text}</div>;
}

function RefreshButton({ onClick }: { onClick: () => void }) {
  return (
    <button className="inline-flex h-8 items-center gap-2 rounded-md border border-border px-3 text-sm font-semibold text-foreground" onClick={onClick} type="button">
      <RefreshCw className="h-4 w-4" aria-hidden />
      Refresh
    </button>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>,
);
