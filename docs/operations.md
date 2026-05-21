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

## Read-only backend service

`github-agent-bridge-backend` is a separate HTTP service for local dashboards and
operator tooling. It is intentionally not part of the executor path: it does not
import the dispatcher, does not claim jobs, does not call GitHub/OpenClaw, and
opens the SQLite database read-only for job queries.

Run it manually:

```bash
github-agent-bridge-backend \
  --db ~/.local/state/github-agent-bridge/bridge.sqlite3 \
  --host 127.0.0.1 \
  --port 8765
```

Endpoints:

```text
GET /healthz
GET /api/status
GET /api/jobs?status=pending&limit=20
```

Keep it bound to `127.0.0.1` unless you put an authenticated reverse proxy in
front of it. The packaged `systemd/github-agent-bridge-backend.service` starts
only this backend; it does not restart or depend on `github-agent-bridge.service`.

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

## Migration context

Initial migration target from the legacy worker:

- `~/.local/bin/pilipilis_inbox_worker.py`
- `~/.local/state/pilipilis/github-worklog.jsonl`
- `~/.local/state/pilipilis/github-active.json`
- `~/.local/state/pilipilis/inbox_state.json`
