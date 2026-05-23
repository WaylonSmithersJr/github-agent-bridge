import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { Activity, AlertTriangle, ArrowLeft, CheckCircle2, ChevronDown, Clock3, Cpu, ExternalLink, Link, RefreshCw, Search, ShieldCheck, TerminalSquare, UserCircle2 } from "lucide-react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
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
      refetchInterval: 15000,
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

function selectedJobIdFromPath(pathname = window.location.pathname) {
  const match = pathname.match(/^\/jobs\/(\d+)\/?$/);
  return match ? Number(match[1]) : null;
}

function App() {
  const [filters, setFilters] = React.useState<JobFilters>({ status: "", repo: "", thread: "", action: "", intent: "" });
  const [selectedJobId, setSelectedJobId] = React.useState<number | null>(() => selectedJobIdFromPath());
  const [pathname, setPathname] = React.useState(() => window.location.pathname);
  const jobRouteId = selectedJobIdFromPath(pathname);
  const isJobDetailRoute = jobRouteId !== null;
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
    source.addEventListener("session_event", () => {
      sessionEvents.refetch();
      transcript.refetch();
      detail.refetch();
      jobs.refetch();
    });
    source.addEventListener("session_tick", () => {
      transcript.refetch();
    });
    source.onerror = () => {
      source.close();
    };
    return () => source.close();
  }, [selectedJobId]);

  React.useEffect(() => {
    const syncFromPath = () => {
      setPathname(window.location.pathname);
      const nextJobId = selectedJobIdFromPath();
      if (nextJobId !== null) setSelectedJobId(nextJobId);
    };
    window.addEventListener("popstate", syncFromPath);
    return () => window.removeEventListener("popstate", syncFromPath);
  }, []);

  const selectJob = React.useCallback((jobId: number) => {
    setSelectedJobId(jobId);
  }, []);

  const counts = metrics.data?.metrics.status_counts ?? {};
  const jobRows = jobs.data?.jobs ?? [];
  const selectedJob = selectedJobId ? (detail.data?.job ?? null) : null;
  const selectedJobInList = selectedJobId !== null && jobRows.some((job) => job.id === selectedJobId);
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

            <section className="grid gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(360px,1fr)]">
              <Panel title="Jobs" action={<RefreshButton onClick={() => jobs.refetch()} />}>
                <Filters filters={filters} onChange={setFilters} />
                {jobs.error ? <Banner tone="error" text={jobs.error.message} /> : null}
                <JobsList jobs={jobRows} loading={jobs.isLoading} selectedJobId={selectedJobId} selectedJob={selectedJob} session={session.data?.session} sessionEvents={sessionEvents.data?.events} transcript={transcript.data?.entries} onSelect={selectJob} />
                {selectedJobId !== null && !selectedJobInList ? <div className="mt-4 md:hidden">{detailStatus}</div> : null}
              </Panel>

              <Panel title="Job detail" className="hidden xl:block xl:self-start xl:sticky xl:top-4">
                {detailStatus}
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
  selectedJobId,
  selectedJob,
  session,
  sessionEvents,
  transcript,
  onSelect,
}: {
  jobs: Job[];
  loading: boolean;
  selectedJobId: number | null;
  selectedJob: Job | null;
  session: SessionCorrelation | undefined;
  sessionEvents: SessionEvent[] | undefined;
  transcript: TranscriptEntry[] | undefined;
  onSelect: (id: number) => void;
}) {
  if (loading && jobs.length === 0) return <EmptyState text="Loading jobs..." />;
  if (jobs.length === 0) return <EmptyState text="No jobs match the current filters." />;
  return (
    <>
      <div className="grid gap-3 md:hidden">
        {jobs.map((job) => (
          <JobCard key={job.id} job={job} selected={selectedJobId === job.id} selectedJob={selectedJob} session={session} sessionEvents={sessionEvents} transcript={transcript} onSelect={onSelect} />
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
              className={cn("cursor-pointer border-b border-border hover:bg-slate-50", selectedJobId === job.id && "bg-blue-50")}
              onClick={() => onSelect(job.id)}
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
              <td className="px-2 py-3 font-mono text-xs">{job.updated_at}</td>
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
  selected,
  selectedJob,
  session,
  sessionEvents,
  transcript,
  onSelect,
}: {
  job: Job;
  selected: boolean;
  selectedJob: Job | null;
  session: SessionCorrelation | undefined;
  sessionEvents: SessionEvent[] | undefined;
  transcript: TranscriptEntry[] | undefined;
  onSelect: (id: number) => void;
}) {
  return (
    <article className={cn("rounded-md border border-border bg-white", selected && "border-blue-300 bg-blue-50/40")}>
      <button className="grid w-full gap-3 p-3 text-left" type="button" onClick={() => onSelect(job.id)}>
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
      {selected ? (
        <div className="border-t border-border p-3">
          {selectedJob ? <JobDetail job={selectedJob} session={session} sessionEvents={sessionEvents} transcript={transcript} compact /> : <EmptyState text="Loading detail..." />}
        </div>
      ) : null}
    </article>
  );
}

function JobDetail({ job, session, sessionEvents, transcript, compact = false }: { job: Job; session: SessionCorrelation | undefined; sessionEvents: SessionEvent[] | undefined; transcript: TranscriptEntry[] | undefined; compact?: boolean }) {
  const shareHref = jobPath(job.id);
  const eventRows = sessionEvents ?? [];
  const transcriptRows = transcript ?? [];
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
      <div>
        <h3 className="mb-2 text-sm font-semibold">Timeline</h3>
        <div className="grid gap-3">
          {(job.worklog ?? []).length > 0 ? (
            job.worklog?.map((entry) => (
              <div key={entry.id} className="border-l-2 border-primary pl-3">
                <div className="text-sm font-semibold">{entry.phase}</div>
                <div className="font-mono text-xs text-muted">{entry.ts}</div>
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
          {eventRows.length > 0 ? (
            eventRows.map((event, index) => (
              <SessionEventRow key={event.id} event={event} defaultOpen={job.status === "running" || index >= eventRows.length - 2} />
            ))
          ) : (
            <EmptyState text={job.status === "running" ? "Waiting for live agent output..." : "No agent activity has been recorded for this session."} />
          )}
        </div>
      </div>
      <div>
        <h3 className="mb-2 text-sm font-semibold">Session transcript</h3>
        <div className="grid max-h-[620px] gap-2 overflow-auto pr-1">
          {transcriptRows.length > 0 ? (
            transcriptRows.map((entry, index) => (
              <TranscriptRow key={`${entry.timestamp ?? "entry"}-${index}`} entry={entry} defaultOpen={job.status === "running" || index >= transcriptRows.length - 2} />
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

function TranscriptRow({ entry, defaultOpen }: { entry: TranscriptEntry; defaultOpen?: boolean }) {
  return (
    <CollapsibleLogSection
      badge={entry.title}
      meta={entry.timestamp ?? ""}
      summary={`${entry.role} · ${entry.kind}`}
      defaultOpen={defaultOpen}
    >
      <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-md bg-slate-950 p-3 font-mono text-xs text-slate-100">{entry.text}</pre>
    </CollapsibleLogSection>
  );
}

function SessionEventRow({ event, defaultOpen }: { event: SessionEvent; defaultOpen?: boolean }) {
  return (
    <CollapsibleLogSection badge={event.event_type} meta={event.ts} summary={event.summary} defaultOpen={defaultOpen}>
      {event.detail ? <pre className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap break-words rounded-md bg-slate-950 p-3 font-mono text-xs text-slate-100">{event.detail}</pre> : null}
    </CollapsibleLogSection>
  );
}

function CollapsibleLogSection({
  badge,
  meta,
  summary,
  defaultOpen,
  children,
}: {
  badge: string;
  meta: string;
  summary: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [isOpen, setIsOpen] = React.useState(Boolean(defaultOpen));
  return (
    <details className="group rounded-md border border-border bg-white" open={isOpen} onToggle={(event) => setIsOpen(event.currentTarget.open)}>
      <summary className="grid cursor-pointer list-none gap-2 p-3 marker:hidden">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex min-w-0 items-center gap-2">
            <ChevronDown className="h-4 w-4 shrink-0 text-muted transition-transform group-open:rotate-180" aria-hidden />
            <span className="rounded-full border border-border px-2 py-0.5 text-xs font-semibold text-muted">{badge}</span>
          </div>
          <span className="font-mono text-xs text-muted">{meta}</span>
        </div>
        <div className="break-words pl-6 text-sm">{summary}</div>
      </summary>
      <div className="border-t border-border px-3 pb-3 pt-1">{children}</div>
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
  return (
    <div className="grid gap-4">
      <div className="grid gap-3 md:grid-cols-3">
        <MiniStat label="Executor" value={data.executor.service} />
        <MiniStat label="Main PID" value={data.executor.pid ? String(data.executor.pid) : "n/a"} />
        <MiniStat label="Running jobs" value={String(data.running_jobs.length)} />
      </div>
      {data.alerts.length > 0 ? <Banner tone="error" text={data.alerts[0]} /> : null}
      <div>
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
      <p className="text-xs text-muted">{data.detail}</p>
    </div>
  );
}

function ProcessRow({ process }: { process: ProcessSample }) {
  const read = process.io_bytes?.read_bytes ?? 0;
  const written = process.io_bytes?.write_bytes ?? 0;
  return (
    <div className="rounded-md border border-border p-3">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-mono">pid {process.pid}</span>
        <span className="rounded-full border border-border px-2 text-xs text-muted">state {process.state}</span>
        <span className="rounded-full border border-border px-2 text-xs text-muted">cpu {process.cpu_ticks}</span>
        <span className="rounded-full border border-border px-2 text-xs text-muted">I/O {read + written} B</span>
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

function MiniStat({ label, value }: { label: string; value: string }) {
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

function compactDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>,
);
