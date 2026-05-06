# GitHub Agent Bridge

Bridge between GitHub notifications and OpenClaw agents.

Goals:

- Ingest GitHub notification emails quickly and durably.
- Persist jobs before acknowledging IMAP progress.
- Process different issues/PRs in parallel.
- Prevent concurrent jobs for the same `repo#number`.
- React with 👀 and dispatch work to the right OpenClaw agent.
- Keep an auditable queue/worklog and failure state.

Initial architecture:

```text
IMAP reader -> SQLite queue -> executor pool -> GitHub reactions + OpenClaw dispatch
                         └── per-work_key lock: owner/repo#number
```

This repo replaces the legacy local script currently living at
`~/.local/bin/pilipilis_inbox_worker.py` once migrated.
