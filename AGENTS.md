# Agent development guide

This repository is the GitHub notification → OpenClaw agent bridge used by Pilipilis.

## Safety first

- Default to `--mode shadow` for local runs. Use `--mode live` only when the operator explicitly asks.
- Never enable `--mark-seen` in development fixtures or shadow tests. It mutates the mailbox.
- Never commit secrets, app passwords, tokens, local DBs, logs, or `~/.config/*` files.
- Treat `enabledRepos` as the canary guardrail. If it is set, jobs outside that repo set must be denied.
- Do not remove the per-`work_key` lock/coalescing behavior without replacing it with an equivalent concurrency guard.
- Prefer adding tests around parser/policy/queue/dispatch behavior before changing production flow.

## Fast start

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
pytest -q
```

## Useful local commands

```bash
# Initialize an isolated DB
DB=/tmp/github-agent-bridge-dev.sqlite3
github-agent-bridge --db "$DB" init-db

# Replay a saved .eml without external side effects
github-agent-bridge --db "$DB" --policy ./policy.example.json replay ./fixtures/example.eml --verbose

# Enqueue a real GitHub issue/PR comment URL as a synthetic trusted notification
github-agent-bridge --db "$DB" --policy ./policy.example.json enqueue-comment-url \
  'https://github.com/gisce/erp/pull/27675#issuecomment-4419572864'

# Process queued jobs without touching GitHub/OpenClaw
github-agent-bridge --db "$DB" --policy ./policy.example.json run --mode shadow --once

# Inspect health

github-agent-bridge --db "$DB" --policy ./policy.example.json status
github-agent-bridge --db "$DB" --policy ./policy.example.json monitor --no-systemd
```

## Architecture contract

Pipeline:

```text
IMAP/eml/manual URL -> Notification -> Policy decision -> SQLite jobs -> executor -> GitHub 👀 + OpenClaw agent
```

Important invariants:

1. Reader must persist or explicitly handle a notification before advancing high-water state.
2. `message_id` is globally unique; duplicates must not create duplicate jobs.
3. Active jobs with the same `work_key` (`owner/repo#number`) must coalesce instead of running concurrently.
4. Different `work_key`s may run in parallel.
5. `shadow` and `dry-run` modes must not call GitHub or OpenClaw.
6. `review_only` work uses a shorter timeout and must not ask agents to modify code.
7. `enabledRepos` is a hard allowlist when non-empty.

## Where to change things

- `parser.py`: classify GitHub notification text and extract repo/thread/comment context.
- `policy.py`: trust, canary scope, actions and routing decisions.
- `queue.py`: durable jobs, coalescing, locking and retry state.
- `dispatch.py`: GitHub reactions and OpenClaw agent command construction/execution.
- `reader.py`: IMAP polling and mailbox mutation.
- `monitor.py`: operational health checks.
- `cli.py`: operational entrypoints and developer tooling.

## Test expectations

Run before handing off or pushing:

```bash
pytest -q
```

For changes that touch CLI behavior, also run the relevant command against a temporary DB. Never test live mode against production unless explicitly requested.
