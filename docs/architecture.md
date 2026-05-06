# Architecture

## Components

1. **Reader**
   - Reads IMAP/GitHub notifications.
   - Extracts stable job identity: `work_key = owner/repo#number`.
   - Persists the job before advancing mailbox high-water marks.

2. **Queue**
   - SQLite-backed durable queue.
   - Stores message ids, UIDs, GitHub ids, status, attempts and timestamps.
   - Coalesces repeated notifications for the same active `work_key`.

3. **Executor pool**
   - Runs multiple jobs concurrently when their `work_key` differs.
   - Enforces a per-`work_key` lock so one PR/issue is processed at a time.
   - Converts dispatch timeouts into `blocked` state without blocking the reader.

4. **Dispatch**
   - Applies 👀 reaction when applicable.
   - Sends an OpenClaw agent task with full GitHub context instructions.

## Non-goals for now

- No Redis/Celery unless SQLite becomes insufficient.
- No long-running agent subprocess inside the IMAP reader.
