# Event ingestion and transport migration

The bridge separates three identities:

- A **receipt** identifies one delivery from one transport. Email uses
  `Message-ID`; a future webhook transport will use `X-GitHub-Delivery`.
- A **GitHub event** identifies the underlying action independently of its
  transport. It is derived only from immutable GitHub object IDs exposed by
  the notification, such as a comment, review, or workflow-run ID.
- A **work key** (`owner/repo#number`) serializes work in one thread. It must
  not deduplicate distinct events in that thread.

`ingest_receipts` makes retries from a transport idempotent. `github_events`
implements first-writer-wins across transports and points every duplicate
receipt at the winning job. Both records and the job are written in one SQLite
transaction, before the IMAP high-water mark advances.

When a notification lacks enough immutable data to prove event identity, the
event key falls back to `<source>:<source-key>`. The bridge deliberately
accepts a possible duplicate rather than risk dropping a legitimate action.

## Transport comparison

| Concern | IMAP | GitHub App webhook |
| --- | --- | --- |
| Trust | Auth headers and GitHub sender checks | Mandatory HMAC-SHA256 signature over raw bytes; optional owner allowlist through owner-specific secrets |
| Idempotency | `Message-ID` receipt | `X-GitHub-Delivery` receipt |
| Cross-source identity | IDs parsed from GitHub URLs | IDs in the structured payload |
| Latency | Polling and mail delivery | Immediate delivery with retries |
| Operations | Mailbox cursor, credentials, formatting drift | Public TLS endpoint, secret rotation, delivery monitoring |

## Gradual rollout

1. **Phase 0 (implemented):** route IMAP through the common transactional
   ingestor while preserving the existing queue and dispatch behavior.
2. **Shadow webhook (implemented):** verify signatures and persist shadow
   receipts, but do not create jobs or claim canonical events. Compare coverage
   and canonical keys with IMAP.
3. **Canary dual ingest:** allow webhook enqueue only for `enabledRepos`.
   The unique event key guarantees that the first source wins.
4. **Webhook primary:** keep IMAP as a delayed fallback until a complete
   operational cycle has no unexplained IMAP-only actionable events.

Phase 1 is exposed as `POST /api/webhooks/github` by the dashboard service.
For a single trusted owner, configure `GITHUB_AGENT_BRIDGE_WEBHOOK_SECRET`;
during rotation, `GITHUB_AGENT_BRIDGE_WEBHOOK_PREVIOUS_SECRET` accepts the old
secret as well. This legacy form accepts any repository signed with that shared
secret.

For multiple organizations or owners, use independent secrets and an explicit
owner allowlist:

```shell
export GITHUB_AGENT_BRIDGE_WEBHOOK_SECRETS_BY_OWNER='{"gisce":["current-gisce-secret","previous-gisce-secret"],"example":["example-secret"]}'
```

Each value is an ordered list of accepted current/rotation secrets. When this
setting is present, a payload whose `repository.full_name` owner is not in the
map is rejected before persistence. Do not reuse a secret across owners: that
would couple rotation and increase the blast radius of a leak.

`GITHUB_AGENT_BRIDGE_WEBHOOK_MAX_BYTES` defaults to 1 MiB. GitHub must send
`Content-Type: application/json`, `X-GitHub-Delivery`, `X-GitHub-Event`, and a
valid `X-Hub-Signature-256` computed over the unmodified request bytes.

### GitHub configuration

Create either a repository webhook under **Settings → Webhooks** or an
organization webhook under **Organization settings → Webhooks**:

1. Set **Payload URL** to `https://<host>/api/webhooks/github`.
2. Set **Content type** to `application/json` and **Secret** to the matching
   configured owner secret.
3. Keep SSL verification enabled and the webhook active.
4. Select individual events: **Issue comments**, **Pull request reviews**,
   **Pull request review comments**, **Commit comments**, and **Workflow runs**.
   Do not select “Send me everything” for Phase 1.

A repository webhook covers only that repository. An organization webhook
covers repositories in that organization and is the recommended deployment.
Multiple organizations and multiple hooks may use the same endpoint when each
owner has its own entry in `GITHUB_AGENT_BRIDGE_WEBHOOK_SECRETS_BY_OWNER`.
GitHub's `X-GitHub-Hook-ID` header keeps their inventory and activity separate.

The endpoint stores only routing metadata, a SHA-256 payload hash, and the
canonical event key in `webhook_shadow_receipts`; it deliberately stores no raw
payload and never creates a queue job. Authenticated operators can inspect
counts, a daily activity series, hook inventory, recent deliveries, duplicate
deliveries, and cross-source event-key matches at
`GET /api/webhooks/github/status`. Here “operators” means users authorized as
dashboard administrators through `GITHUB_AGENT_BRIDGE_DASHBOARD_ADMIN_USERS`
or `GITHUB_AGENT_BRIDGE_DASHBOARD_ADMIN_TEAMS`; other authenticated dashboard
users receive HTTP 403 and unauthenticated requests receive HTTP 401.
Receipt details are retained for 30 days by default and pruned during ingestion;
set `GITHUB_AGENT_BRIDGE_WEBHOOK_RETENTION_DAYS` to change that window. Raw
payloads are never retained.

The maintained event inventory and support levels are in
[`webhook-events.md`](webhook-events.md).

Comment and review `edited` deliveries are observed under a distinct key and
do not retrigger work. Phase 2 must make an explicit policy decision before
any non-`created` action can enqueue a job.

Webhook enqueueing must not be enabled until recovery of persisted-but-
unprocessed receipts and divergence metrics have been validated in production.
