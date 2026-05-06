# Architecture

## Components

### Reader

`ImapReader` fetches GitHub notification emails, parses basic metadata and enqueues durable `Notification` jobs. It does **not** react on GitHub or dispatch agents.

Critical invariant: advance `last_uid` only after a notification has been durably queued or safely ignored.

### Queue

`JobQueue` is backed by SQLite/WAL.

Tables:

- `jobs`: durable work items and execution state.
- `coalesced_notifications`: extra emails folded into an already active `work_key`.
- `state`: mailbox high-water and future cursors.
- `worklog`: audit trail.

### Executor pool

`ExecutorPool` claims pending jobs using this rule:

```sql
status = 'pending'
AND NOT EXISTS running job with same work_key
```

This allows parallelism across unrelated PRs/issues while serializing a single thread.

### Dispatch

Dispatch has two external side effects:

1. apply GitHub 👀 reaction when possible;
2. send one OpenClaw agent task with a prompt that forces full context loading.

Failure is contained to the job: `blocked`, `last_error`, lock released.
