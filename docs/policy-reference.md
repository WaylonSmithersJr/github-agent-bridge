# `policy.json` reference

`policy.json` controls which GitHub notifications the bridge trusts, which repositories are in scope, which actions are automatic, and where OpenClaw agent work is delivered.

Default path in the packaged CLI/systemd examples:

```text
~/.config/github-agent-bridge/policy.json
```

The policy is loaded by commands that make decisions or dispatch work, for example:

```bash
gab --policy ~/.config/github-agent-bridge/policy.json read-imap-once ...
gab --policy ~/.config/github-agent-bridge/policy.json run --mode live ...
gab --policy ~/.config/github-agent-bridge/policy.json enqueue-comment-url ...
```

## Complete example

```json
{
  "source": {
    "from": "notifications@github.com",
    "requiredAuth": ["spf=pass", "dkim=pass", "dmarc=pass"],
    "requiredUrlPrefix": "https://github.com/",
    "messageIdDomain": "github.com"
  },
  "trustedRepos": ["vermutech/stats"],
  "trustedOrgs": ["gisce"],
  "enabledRepos": ["gisce/erp"],
  "repoRoutes": {
    "canprats/governance": {
      "agent": "canprats-core",
      "channel": "telegram",
      "to": "-1003731933363"
    }
  },
  "orgRoutes": {
    "gisce": {
      "agent": "gisce-developer",
      "channel": "telegram",
      "to": "-1003972920100"
    }
  },
  "actions": {
    "auto": ["archive_notification", "sync_after_merge"],
    "ask": [],
    "trustedAuto": ["reply_comment", "open_issue", "docs_update", "content_change"],
    "deny": ["merge_main", "org_permissions_change", "manage_secrets", "delete_remote_repo_or_branch"]
  }
}
```

## Top-level keys

| Key | Type | Default | Meaning |
| --- | --- | --- | --- |
| `source` | object | built-in GitHub defaults | Defines which notifications count as trusted GitHub source mail. |
| `trustedRepos` | array of strings | `[]` | Exact `owner/repo` names trusted for `trustedAuto` actions. Case-insensitive. |
| `trustedOrgs` | array of strings | `[]` | GitHub org/user names trusted for all repos under that owner. Case-insensitive. |
| `enabledRepos` | array of strings | `[]` | Optional hard allowlist/canary scope. If non-empty, all repos not listed here are denied before other checks. Case-insensitive. |
| `repoRoutes` | object | `{}` | Exact per-repo delivery routes. Takes precedence over `orgRoutes`. |
| `orgRoutes` | object | `{}` | Per-owner delivery routes used when no `repoRoutes` entry matches. |
| `actions` | object | built-in action defaults | Maps classified notification actions to policy decisions. |

Unknown top-level keys are ignored by the current implementation.

## `source`

`source` controls source trust. A notification must pass source trust before it can become `auto`, `auto_trusted`, or `ask`.

| Key | Type | Default | Meaning |
| --- | --- | --- | --- |
| `from` | string | `notifications@github.com` | Required substring in the decoded email `From` header. |
| `requiredUrlPrefix` | string | `https://github.com/` | At least one extracted URL must start with this prefix. |
| `messageIdDomain` | string | `github.com` | Required substring in the email `Message-ID`. |
| `requiredAuth` | array of strings | currently documented only | Intended SPF/DKIM/DMARC requirements. See note below. |

Current auth behavior:

- Parsed email notifications with auth results must have `spf`, `dkim`, and `dmarc` truthy.
- Synthetic notifications, such as `gab enqueue-comment-url`, set all three auth values to `true`.
- The exact strings in `source.requiredAuth` are not currently interpreted; they document the expected policy but the code currently checks the three booleans directly.

Source trust fails when any of these are false:

```text
source.from is in From header
AND auth is OK
AND at least one GitHub URL has source.requiredUrlPrefix
AND Message-ID contains source.messageIdDomain
```

If source trust fails, the decision is always `deny`.

## `trustedRepos`

Exact repositories trusted for `trustedAuto` actions.

Example:

```json
{
  "trustedRepos": ["gisce/erp", "vermutech/stats"]
}
```

A repo listed here makes `repo_trusted(repo)` true even if its owner is not in `trustedOrgs`.

## `trustedOrgs`

Owners trusted for all repositories under that owner.

Example:

```json
{
  "trustedOrgs": ["gisce", "canprats"]
}
```

`gisce` trusts `gisce/erp`, `gisce/other`, etc., unless `enabledRepos` narrows the active scope.

## `enabledRepos`

Hard allowlist for canary/live scope.

Default:

```json
{
  "enabledRepos": []
}
```

Semantics:

- Empty array: no extra scope restriction.
- Non-empty array: only listed repos may be processed.
- Repos not listed are denied before source trust, action policy, or routes are considered.

Example canary policy:

```json
{
  "trustedOrgs": ["gisce"],
  "enabledRepos": ["gisce/erp"]
}
```

Result:

| Repo | Result |
| --- | --- |
| `gisce/erp` | Eligible for normal decisions. |
| `gisce/other` | `deny`. |
| `canprats/governance` | `deny`. |

This is the preferred key for staged rollout from the legacy inbox worker to the bridge.

## `repoRoutes` and `orgRoutes`

Routes decide where the OpenClaw agent task is delivered after a job is accepted.

Route object:

| Key | Type | Meaning |
| --- | --- | --- |
| `agent` | string or null | OpenClaw agent id, for example `gisce-developer`. |
| `channel` | string or null | Delivery channel, for example `telegram`. |
| `to` | string or null | Delivery target, for example a Telegram chat id. |

Route precedence:

1. Exact `repoRoutes[owner/repo]`.
2. Owner-level `orgRoutes[owner]`.
3. CLI defaults passed to `gab run` with `--channel` and `--to`.
4. Dispatch fallback: when no route agent is configured and the repo owner is `gisce`, the dispatcher uses `gisce-developer`.

Example:

```json
{
  "repoRoutes": {
    "canprats/governance": {
      "agent": "canprats-core",
      "channel": "telegram",
      "to": "-1003731933363"
    }
  },
  "orgRoutes": {
    "gisce": {
      "agent": "gisce-developer",
      "channel": "telegram",
      "to": "-1003972920100"
    }
  }
}
```

With this policy:

| Repo | Route |
| --- | --- |
| `canprats/governance` | `canprats-core` to `-1003731933363`. |
| `gisce/erp` | `gisce-developer` to `-1003972920100`. |
| `other/repo` | CLI default channel/target, no configured agent unless dispatch fallback applies. |

Routes do not grant trust. A repo can have a route and still be denied by source/action/scope policy.

## `actions`

The parser classifies each GitHub notification into one action. `actions` maps that action to a policy decision.

Supported action names currently produced by the parser:

| Action | Produced when | Typical meaning |
| --- | --- | --- |
| `archive_notification` | Notification is routine and does not mention/assign/request the bot. | Persist as handled without agent work. |
| `sync_after_merge` | Notification text contains `merged`. | Do post-merge cleanup/sync behavior. |
| `reply_comment` | Bot mentioned, review requested, Copilot review, or PR review notification. | React 👀 and dispatch agent work/reply. |
| `open_issue` | Bot assigned to an issue/PR. | React 👀 and dispatch agent work for the assigned thread. |

Other action names can appear in policy, but they have no effect until parser/dispatcher code produces or handles them.

### `actions.auto`

Actions in `auto` are accepted for any trusted source notification, regardless of `trustedRepos`/`trustedOrgs`.

Default:

```json
{
  "auto": ["archive_notification", "sync_after_merge"]
}
```

Decision produced: `auto`.

Queue status produced: `done` immediately at enqueue time.

Use `auto` only for low-risk internal handling that should not require repo trust.

### `actions.trustedAuto`

Actions in `trustedAuto` are accepted only when:

1. source trust passes, and
2. repo is trusted by `trustedRepos` or `trustedOrgs`, and
3. repo passes `enabledRepos` if that list is non-empty.

Decision produced:

- `auto_trusted` when repo is trusted.
- `ask` when repo is not trusted.

Queue status produced:

- `pending` for `auto_trusted`.
- `waiting_approval` for `ask`.

Typical values:

```json
{
  "trustedAuto": ["reply_comment", "open_issue"]
}
```

The example policy may include future action labels such as `docs_update` or `content_change`. Those are harmless until the parser emits them.

### `actions.ask`

Actions in `ask` produce `ask` for trusted source notifications that are not already handled by `auto` or `trustedAuto`.

Decision produced: `ask`.

Queue status produced: `waiting_approval`.

Current bridge behavior records these jobs but does not implement a human approval UI in this package.

### `actions.deny`

`deny` is documented for operator clarity and future policy expansion.

Current implementation does not read `actions.deny` directly. Any action that does not match `auto`, `trustedAuto`, or `ask` becomes `deny` by default.

Decision produced: `deny`.

Queue status produced: `denied`.

## Decision order

The policy decision function applies checks in this order:

1. If `enabledRepos` is non-empty and `ctx.repo` is not listed: `deny`.
2. If source trust fails: `deny`.
3. If `action` is in `actions.auto`: `auto`.
4. If `action` is in `actions.trustedAuto`:
   - trusted repo/org: `auto_trusted`;
   - otherwise: `ask`.
5. If `action` is in `actions.ask`: `ask`.
6. Otherwise: `deny`.

## Decisions and queue statuses

| Decision | Queue status | External side effects |
| --- | --- | --- |
| `auto` | `done` | No executor dispatch. Used for automatic handling recorded as done. |
| `auto_trusted` | `pending` | Executor may react 👀 and dispatch OpenClaw agent in `live` mode. |
| `ask` | `waiting_approval` | No executor dispatch until retried/changed manually. |
| `deny` | `denied` | No executor dispatch. |

Run mode still matters:

| Run mode | GitHub reaction | OpenClaw dispatch |
| --- | --- | --- |
| `shadow` | skipped | skipped |
| `dry-run` | skipped | skipped, command rendered as successful detail |
| `live` | executed | executed |

## Case normalization

The implementation lowercases:

- `trustedRepos`
- `trustedOrgs`
- `enabledRepos`
- `repoRoutes` keys
- `orgRoutes` keys
- extracted `ctx.repo`

Use lowercase in policy files for readability.

## Minimal policies

### Shadow all trusted GISCE repos

```json
{
  "trustedOrgs": ["gisce"],
  "actions": {
    "auto": ["archive_notification", "sync_after_merge"],
    "trustedAuto": ["reply_comment", "open_issue"],
    "ask": []
  }
}
```

### Live canary for one repo

```json
{
  "trustedOrgs": ["gisce"],
  "enabledRepos": ["gisce/erp"],
  "orgRoutes": {
    "gisce": {
      "agent": "gisce-developer",
      "channel": "telegram",
      "to": "-1003972920100"
    }
  },
  "actions": {
    "auto": ["archive_notification", "sync_after_merge"],
    "trustedAuto": ["reply_comment", "open_issue"],
    "ask": []
  }
}
```

### Require approval for comments on untrusted repos

```json
{
  "trustedRepos": [],
  "trustedOrgs": [],
  "actions": {
    "auto": ["archive_notification"],
    "trustedAuto": ["reply_comment", "open_issue"],
    "ask": ["reply_comment", "open_issue"]
  }
}
```

With this policy, trusted source notifications for comment/assignment actions become `ask` because the repo is not trusted.

## Operational notes

- Policy changes affect new enqueue decisions. Existing jobs keep the decision/status already stored in SQLite.
- Restart the long-running executor after changing routes or run-mode related environment, because it loads policy at process start.
- The periodic IMAP reader loads policy on each invocation.
- Use `gab monitor` after policy changes to verify queue health.
- Use `gab jobs --limit 20` to inspect recent decisions.
