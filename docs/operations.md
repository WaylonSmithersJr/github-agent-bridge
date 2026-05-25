# Operations

This guide is for running and monitoring the bridge.

> **Operator rule:** prefer `gab`. The long `github-agent-bridge` entrypoint is kept only for backwards compatibility.

## Runtime layout

| Item | Typical path |
| --- | --- |
| Database | `~/.local/state/github-agent-bridge/bridge.sqlite3` |
| Policy | `~/.config/github-agent-bridge/policy.json` |
| Environment | `systemd/env.example` copied to a private env file |
| Units | `systemd/*.service`, `systemd/*.timer` |
| Reader wrapper | packaged `github-agent-bridge-reader-run` console script |

## Production commands

The reader systemd timer uses `github-agent-bridge-reader-run`, a small packaged
wrapper around `gab read-imap-once` that reads `GITHUB_AGENT_BRIDGE_*`
environment variables, quotes Gmail mailbox names with spaces for IMAP, and
conditionally adds `--mark-seen`.


Executor pool:

```bash
gab --db ~/.local/state/github-agent-bridge/bridge.sqlite3 \
  --policy ~/.config/github-agent-bridge/policy.json \
  run --mode live --workers 4 --review-timeout 900 --work-timeout 3600
```

Reader timer job:

```bash
gab --db ~/.local/state/github-agent-bridge/bridge.sqlite3 \
  --policy ~/.config/github-agent-bridge/policy.json \
  read-imap-once \
  --email "$GITHUB_AGENT_BRIDGE_EMAIL" \
  --password "$GITHUB_AGENT_BRIDGE_PASSWORD" \
  --mark-seen
```

## Health checks

```bash
gab --db ~/.local/state/github-agent-bridge/bridge.sqlite3 monitor
gab --db ~/.local/state/github-agent-bridge/bridge.sqlite3 monitor --json
```

The monitor exits:

| Exit code | Meaning |
| --- | --- |
| `0` | healthy |
| `2` | alert detected |

It checks:

- executor service active;
- reader timer active;
- last reader service result;
- blocked jobs;
- pending jobs older than 300 seconds;
- running jobs older than review/work thresholds.

By default the monitor command also writes bounded observability rows to the
bridge database:

- `process_samples`: recent executor child process trees, total CPU ticks, total
  I/O bytes, running job ids and whether the sample changed since the previous
  monitor run;
- `job_progress`: compact per-job semantic and visible progress heartbeats,
  separate from the longer audit/worklog timeline;
- `alerts`: active and resolved monitor alert observations with first/last seen
  timestamps and observation counts.

Process sample retention defaults to 24 hours. Override it with
`GITHUB_AGENT_BRIDGE_PROCESS_SAMPLE_RETENTION_SECONDS` or:

```bash
gab --db ~/.local/state/github-agent-bridge/bridge.sqlite3 \
  monitor --process-sample-retention-seconds 21600
```

Use `--no-persist-observability` for ad hoc monitor runs that should not write
observability records.

Running-job age is not treated as a failure signal by itself. The monitor uses
the latest semantic heartbeat, visible OpenClaw output, and persisted
CPU/I/O/PID-tree activity to decide whether an old running job looks stalled.
Use `--progress-warn-seconds` to tune how long a running job can go without a
semantic or visible progress update before the monitor considers it quiet.
The alert wrapper uses the same composite stalled-job alert before automatic
unlock or child termination. It does not unlock every old running job; it passes
only the job ids that the monitor flagged as stalled.

## Dashboard API service

`github-agent-bridge-dashboard` is a separate FastAPI service for local
dashboards and operator tooling. It is intentionally not part of the executor
path: it does not import the dispatcher, does not claim jobs, does not call
OpenClaw, and opens the SQLite database read-only for job queries.

The service also serves the built React dashboard at `/` and dedicated job
views at `/jobs/{id}`. Operators can share a job URL to open the dashboard with
that job's session, worklog, activity feed and GitHub links selected. The UI is
a Vite + React + TypeScript app styled with Tailwind and operational components,
using TanStack Query for API state and Recharts for percentile charts.
The process activity API and dashboard distinguish live executor process state,
persisted process activity, semantic job progress, and visible transcript/output
progress so operators can tell whether a running job is merely alive or actually
making useful progress.
Timestamps stay stored and returned by the API in UTC, while the browser renders
them in the viewer's local timezone from `Intl.DateTimeFormat`; hovering a
rendered timestamp shows the UTC value.
Production serves the static bundle from
`src/github_agent_bridge/dashboard_static`.

The API uses GitHub OAuth sessions by default. Configure these values in
`~/.config/github-agent-bridge/env`:

```text
GITHUB_AGENT_BRIDGE_DASHBOARD_SECRET_KEY=replace-with-random-secret
GITHUB_OAUTH_CLIENT_ID=replace-with-github-oauth-client-id
GITHUB_OAUTH_CLIENT_SECRET=replace-with-github-oauth-client-secret
GITHUB_AGENT_BRIDGE_DASHBOARD_ALLOWED_USERS=alice,bob
GITHUB_AGENT_BRIDGE_DASHBOARD_ALLOWED_ORGS=example-org
```

See [`dashboard-github-oauth.md`](dashboard-github-oauth.md) for the GitHub
OAuth App creation steps, callback URL, scopes, allowlists, reverse proxy notes
and troubleshooting.

Run it manually:

```bash
github-agent-bridge-dashboard \
  --db ~/.local/state/github-agent-bridge/bridge.sqlite3 \
  --host 127.0.0.1 \
  --port 8765
```

Frontend development:

```bash
cd dashboard
npm install
npm run dev
```

Build the packaged UI bundle:

```bash
cd dashboard
npm run build
```

Endpoints:

```text
GET /
GET /jobs/{id}
GET /api/health
GET /api/status
GET /api/jobs?status=pending&repo=pilipilisbot/github-agent-bridge&limit=20
GET /api/jobs/{id}
GET /api/jobs/{id}/logs
GET /api/jobs/{id}/session
GET /api/jobs/{id}/session/events
GET /api/jobs/{id}/session/stream
GET /api/metrics/summary
GET /api/processes
GET /api/alerts
GET /api/events/stream
```

Keep it bound to `127.0.0.1` unless you put an authenticated reverse proxy in
front of it. The packaged `systemd/github-agent-bridge-dashboard.service` starts
only this dashboard API; it does not restart or depend on
`github-agent-bridge.service`.

Current scope covers the read-only API, OAuth/session guard, job detail, logs,
summary metrics, an initial read-only React operations UI, a live `/proc`
snapshot of executor child processes plus persisted monitor sample history
through `GET /api/processes`, persistent monitor alert observations through
`GET /api/alerts`, the GitHub login that triggered a job when it can be derived
from the notification or GitHub API, and safe
OpenClaw session correlation through `GET /api/jobs/{id}/session`. New
dispatches use a deterministic `github-agent-bridge-job-{id}` OpenClaw session
id so operators can correlate a bridge job with the OpenClaw session that ran
it, and the dispatcher enables OpenClaw verbose mode for these sessions so tool
calls and command output are available to the live dashboard stream. The React route `/jobs/{id}` is a focused job detail page for sharing a
single job/session, with a link back to the generic dashboard. The dashboard
records bounded, redacted bridge-side session events when a job is claimed,
while OpenClaw stdout/stderr is emitted, dispatched and finished. The dashboard
records OpenClaw CLI output from flushed byte chunks rather than waiting for
newline-terminated lines, so partial interactive output can appear before the
OpenClaw process exits. The dashboard renders activity and transcript logs as
compact collapsible sections so long sessions can be scanned like GitHub Actions
or Copilot session output. Consecutive OpenClaw stdout/stderr chunks are grouped
into one row with a count and a one-line preview, and routine stdout groups stay
collapsed by default so plugin startup noise does not dominate the page.
Operators can read them with
`GET /api/jobs/{id}/session/events` or subscribe to
`GET /api/jobs/{id}/session/stream` for SSE updates. The stream carries new
session events and transcript entries directly, including already-recorded live
transcript entries when a browser opens the page after the job has started, with
heartbeat events and proxy buffering disabled for long-lived HTTPS connections. While a job is still
running, live redacted OpenClaw stdout/stderr is also exposed as transcript
entries. The dashboard also reads OpenClaw's live trajectory file
`github-agent-bridge-job-{id}.trajectory.jsonl`, so tool calls and tool results
can stream before OpenClaw writes the final session transcript file. The
dashboard also exposes redacted OpenClaw transcript entries for the correlated
session through `GET /api/jobs/{id}/session/transcript`. By default it looks up
`~/.openclaw/agents/github/sessions/sessions.json`, or the path set in
`GITHUB_AGENT_BRIDGE_OPENCLAW_SESSION_STORE`, and only returns entries for the
job's deterministic session id. Transcript text is secret-redacted and truncated
before it is returned to the authenticated dashboard. The process activity panel
uses persisted process samples for a compact CPU history line chart when monitor
samples exist, and falls back to the live executor snapshot otherwise.

## Operational SLOs

| Signal | Target |
| --- | --- |
| Oldest pending job | below 2 minutes |
| Review-only job | normally below 15 minutes |
| Implementation job | normally below 60 minutes |
| Blocked dispatch | must not block unrelated PRs/issues |
| Mailbox cursor | must not advance before durable queue/ignore |

## Common operator tasks

### Inspect queue status

```bash
gab --db ~/.local/state/github-agent-bridge/bridge.sqlite3 status
gab --db ~/.local/state/github-agent-bridge/bridge.sqlite3 jobs --limit 20
```

Jobs include `trigger_actor` and `trigger_actor_avatar_url` when the bridge can
identify the GitHub user that caused the notification. New GitHub notification
jobs derive the login from the notification sender and use GitHub's avatar URL.
Existing jobs can be backfilled from stored GitHub context:

```bash
gab --db ~/.local/state/github-agent-bridge/bridge.sqlite3 \
  backfill-trigger-actors --dry-run
gab --db ~/.local/state/github-agent-bridge/bridge.sqlite3 \
  backfill-trigger-actors
```

### Inspect feedback learning rules

Trusted actionable GitHub notifications are captured into the bridge database as
feedback candidates. Inspect candidates with:

```bash
gab --db ~/.local/state/github-agent-bridge/bridge.sqlite3 \
  feedback-events --scope repo:owner/name --limit 20
```

Curated rules injected into agent prompts can be inspected with:

```bash
gab --db ~/.local/state/github-agent-bridge/bridge.sqlite3 \
  feedback-rules --scope repo:owner/name --min-confidence 0.5
```

Capture is controlled by `policy.json` `feedbackLearning.enabled`; the prompt
threshold comes from `feedbackLearning.minConfidence`.

Run an autonomous learning pass with:

```bash
gab --db ~/.local/state/github-agent-bridge/bridge.sqlite3 \
  --policy ~/.config/github-agent-bridge/policy.json \
  feedback-learn
```

The learning pass calls an LLM through OpenClaw, classifies unprocessed
`feedback_events`, and writes `feedback_rule_proposals`. High-confidence
reusable lessons are promoted automatically to `feedback_rules`; task-specific
comments are rejected and never reach agent prompts. It uses the dedicated
`feedbackLearning.sessionId` OpenClaw session and does not deliver chat output.
The classifier prompt defaults to packaged `prompt_rules/feedback_classifier.md`;
override it with `policy.json` `promptOverrides.rules.feedback_classifier`.

The learning pass model is independent from the model used by normal GitHub
work agents. Configure it in `policy.json`:

```json
{
  "feedbackLearning": {
    "model": "gpt-5.4-mini",
    "thinking": "low",
    "sessionId": "github-agent-bridge-feedback"
  }
}
```

For one-off runs, CLI flags take precedence over policy:

```bash
gab --db ~/.local/state/github-agent-bridge/bridge.sqlite3 \
  --policy ~/.config/github-agent-bridge/policy.json \
  feedback-learn --model gpt-5.4-mini --thinking low
```

If no model is set by CLI or policy, OpenClaw uses its default model. The model
used for each classification is stored in `feedback_rule_proposals.model`.

For unattended operation, install and enable:

```bash
systemctl --user enable --now github-agent-bridge-feedback.timer
```

Manual rule insertion remains available for operator backfills:

```bash
gab --db ~/.local/state/github-agent-bridge/bridge.sqlite3 \
  feedback-rule-add \
  --scope repo:owner/name \
  --type style_preference \
  --confidence 0.8 \
  --source-event github-agent-bridge-... \
  --rule 'Answer with concrete repository-specific evidence.'
```

### Retry a blocked job

```bash
gab --db ~/.local/state/github-agent-bridge/bridge.sqlite3 retry <job-id>
```

For `reply_comment` jobs, the executor checks GitHub before dispatching. If the
authenticated bot has already commented after the triggering issue comment, the
job is completed without dispatch to avoid duplicate replies.

Dismiss an obsolete blocked job after auditing it:

```bash
gab --db ~/.local/state/github-agent-bridge/bridge.sqlite3 dismiss <job-id> --reason "already handled"
```

### Unlock stale running jobs

```bash
gab --db ~/.local/state/github-agent-bridge/bridge.sqlite3 unlock-stale --older-than 1800
```

Limit a manual unlock to audited job ids when other long-running jobs are still
making progress:

```bash
gab --db ~/.local/state/github-agent-bridge/bridge.sqlite3 unlock-stale --older-than 1800 --job-id 123
```

## Migration context

Initial migration target from the legacy worker:

- `~/.local/bin/pilipilis_inbox_worker.py`
- `~/.local/state/pilipilis/github-worklog.jsonl`
- `~/.local/state/pilipilis/github-active.json`
- `~/.local/state/pilipilis/inbox_state.json`
