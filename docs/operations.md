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

## Production commands

The reader systemd timer uses `github-agent-bridge-reader-run`, a small installed wrapper around `gab read-imap-once` that reads `GITHUB_AGENT_BRIDGE_*` environment variables and conditionally adds `--mark-seen`.


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

Trusted actionable GitHub notifications are captured into the bridge database.
The compact rules shown to agents can be inspected with:

```bash
gab --db ~/.local/state/github-agent-bridge/bridge.sqlite3 \
  feedback-rules --scope repo:owner/name --min-confidence 0.5
```

### Retry a blocked job

```bash
gab --db ~/.local/state/github-agent-bridge/bridge.sqlite3 retry <job-id>
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
