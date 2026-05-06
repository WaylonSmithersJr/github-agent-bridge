# Operations

Initial migration target from legacy worker:

- `~/.local/bin/pilipilis_inbox_worker.py`
- `~/.local/state/pilipilis/github-worklog.jsonl`
- `~/.local/state/pilipilis/github-active.json`
- `~/.local/state/pilipilis/inbox_state.json`

Operational SLOs:

- Oldest pending GitHub job age should stay below 2 minutes.
- A blocked dispatch must not block unrelated PRs/issues.
- No UID may be advanced before its notification is durably queued or handled.
