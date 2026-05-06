# Failure modes

## IMAP burst backlog

Reader must enqueue all new UIDs oldest-first and never wait for agent completion.

## Agent dispatch timeout

Mark the job as `blocked`, store stderr/stdout summary, release the `work_key` lock.

## Duplicate notifications for same PR/issue

If a job is already `pending`/`running` for the same `work_key`, coalesce the notification
instead of creating parallel agent work for the same thread.

## Reaction failure

Continue dispatching the agent if policy allows it, but record the reaction failure.
