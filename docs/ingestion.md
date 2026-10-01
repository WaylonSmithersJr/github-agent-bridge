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
| Trust | Auth headers and GitHub sender checks | Mandatory HMAC-SHA256 signature over raw bytes, plus installation/repository policy |
| Idempotency | `Message-ID` receipt | `X-GitHub-Delivery` receipt |
| Cross-source identity | IDs parsed from GitHub URLs | IDs in the structured payload |
| Latency | Polling and mail delivery | Immediate delivery with retries |
| Operations | Mailbox cursor, credentials, formatting drift | Public TLS endpoint, secret rotation, delivery monitoring |

## Gradual rollout

1. **Phase 0 (implemented):** route IMAP through the common transactional
   ingestor while preserving the existing queue and dispatch behavior.
2. **Shadow webhook:** verify signatures and persist receipts/events, but do
   not create jobs. Compare coverage and canonical keys with IMAP.
3. **Canary dual ingest:** allow webhook enqueue only for `enabledRepos`.
   The unique event key guarantees that the first source wins.
4. **Webhook primary:** keep IMAP as a delayed fallback until a complete
   operational cycle has no unexplained IMAP-only actionable events.

Webhook ingestion must not be enabled until raw-body signature verification,
payload-size limits, secret rotation, recovery of persisted-but-unprocessed
receipts, and metrics for source divergence are in place.
