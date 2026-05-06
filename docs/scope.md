# Scope

`github-agent-bridge` is intentionally GitHub-only.

It should not become a generic inbox assistant. The intended production split is:

```text
Generic inbox worker
  ├── ordinary email triage / reminders / calendar invites / status emails
  └── GitHub notifications are delegated to github-agent-bridge

GitHub Agent Bridge
  ├── classify GitHub notification
  ├── enqueue durable GitHub job
  ├── coalesce per owner/repo#number
  ├── react 👀
  └── dispatch OpenClaw agent work
```

## Mailbox ownership rule

The bridge may scan the same mailbox with its own high-water cursor, but it must only mutate
GitHub notification messages. Non-GitHub mail is ignored and left untouched for the generic worker.

If the generic worker becomes the sole IMAP owner later, it can call `github-agent-bridge enqueue-json`
for GitHub messages instead of letting the bridge read IMAP directly.
