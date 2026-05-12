# GitHub Agent Bridge

Reusable bridge between GitHub notifications and OpenClaw agents.

It is designed to replace one-off inbox scripts with a durable, auditable pipeline:

```text
IMAP reader -> SQLite queue -> executor pool -> GitHub 👀 + OpenClaw agent dispatch
                         └── per-work_key lock: owner/repo#number
```

## What it solves

- The IMAP reader is fast and never waits for agent work.
- Jobs are persisted before mailbox high-water marks advance.
- Different issues/PRs can run in parallel.
- The same issue/PR cannot run concurrently (`work_key = owner/repo#number`).
- Duplicate notifications for an active thread are coalesced.
- Dispatch timeout/failure marks one job as `blocked` without blocking unrelated work.
- OpenClaw agent runs get explicit timeouts: 900s for review-only jobs and 3600s for implementation work by default.


## Scope boundary

This project is GitHub-only. Generic email triage, calendar/status emails and personal inbox logic should live in a separate generic inbox worker. The bridge must not mutate non-GitHub messages. See `docs/scope.md`.

## Releases

Versions, tags, changelog and GitHub Releases are automated from Conventional Commits on `main`; see `docs/releases.md`.

## Development

Agents should read `AGENTS.md` first. Developer workflow and safe manual replay commands live in `docs/development.md`.

## CLI

Prefer the short `gab` command. The long `github-agent-bridge` entrypoint remains as a backwards-compatible alias for existing installs/systemd units.

```bash
gab --db ~/.local/state/github-agent-bridge/bridge.sqlite3 init-db
gab --db ~/.local/state/github-agent-bridge/bridge.sqlite3 read-imap-once   --email "$EMAIL" --password "$APP_PASSWORD"
gab --db ~/.local/state/github-agent-bridge/bridge.sqlite3 run --mode shadow --workers 4
# live executor, explicit long-running GitHub work timeout profile
gab --db ~/.local/state/github-agent-bridge/bridge.sqlite3 run --mode live --workers 4 --review-timeout 900 --work-timeout 3600
gab --db ~/.local/state/github-agent-bridge/bridge.sqlite3 status
gab --db ~/.local/state/github-agent-bridge/bridge.sqlite3 monitor
# safely enqueue a specific GitHub issue/PR comment URL
gab --db /tmp/github-agent-bridge-dev.sqlite3 --policy ./policy.example.json enqueue-comment-url \
  "https://github.com/gisce/erp/pull/27675#issuecomment-4419572864"
```

## Policy

By default the bridge is conservative. Provide a JSON policy with trusted repos/orgs and routes. See `docs/policy-reference.md` for the full reference:

```json
{
  "trustedOrgs": ["gisce"],
  "enabledRepos": ["gisce/erp"],
  "actions": {
    "auto": ["archive_notification", "sync_after_merge"],
    "trustedAuto": ["reply_comment", "open_issue"],
    "ask": ["reply_comment", "open_issue"]
  },
  "orgRoutes": {
    "gisce": {"agent": "gisce-developer", "channel": "telegram", "to": "-1003972920100"}
  }
}
```

## Safe rollout

Use `replay`, `read-imap-once` without `--mark-seen`, and `run --mode shadow` before enabling `run --mode live`. See `docs/shadow-canary.md`.

## Current status

This is an implementation scaffold with reusable components and tests. It does not yet replace the production legacy worker automatically. Use the systemd units under `systemd/` for shadow/canary deployment.
