# Shadow and canary rollout

The safe path to production is deliberately staged.

## 1. Offline replay

Export recent GitHub notification emails as `.eml` files or an mbox and replay them:

```bash
github-agent-bridge --db /tmp/github-agent-bridge-shadow.sqlite3 init-db
github-agent-bridge --db /tmp/github-agent-bridge-shadow.sqlite3 --policy ./policy.json replay ./fixtures/github-emails --verbose
github-agent-bridge --db /tmp/github-agent-bridge-shadow.sqlite3 jobs --limit 50
```

No GitHub reaction, no OpenClaw agent dispatch and no IMAP mutation happen in replay.

## 2. Shadow IMAP

Read live IMAP with an independent bridge DB cursor, but do not mark messages seen:

```bash
github-agent-bridge --db ~/.local/state/github-agent-bridge-shadow/bridge.sqlite3 read-imap-once \
  --email "$EMAIL" --password "$APP_PASSWORD"
github-agent-bridge --db ~/.local/state/github-agent-bridge-shadow/bridge.sqlite3 run --mode shadow --once --workers 4
```

Important: `read-imap-once` only marks GitHub messages seen when `--mark-seen` is explicitly passed.
Do not pass it during shadow mode.

## 3. Dry-run executor

`--mode dry-run` claims jobs and renders intended side effects as successful without executing external calls.
Use this to validate routing and prompts.

## 4. Canary live

Use a policy that trusts only one low-risk repo/org, then run live:

```bash
github-agent-bridge --policy ./policy-canary.json run --mode live --workers 2
```

Only after canary is clean should the legacy worker stop handling GitHub notifications.

## Rollback

Stop the bridge systemd unit and keep/restore the legacy inbox worker. The bridge DB is append-only enough to inspect what happened after rollback.
