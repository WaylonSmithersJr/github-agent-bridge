# Development workflow

This guide is for humans and agents changing the bridge safely.

## Local setup

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
pytest -q
```

## Fast feedback loop

```mermaid
flowchart LR
    A[Change code/docs] --> B[pytest -q]
    B --> C[shadow replay]
    C --> D[review diff]
    D --> E[commit]
```

## Safe manual replay

Use `enqueue-comment-url` instead of hand-writing notification JSON.

```bash
DB=/tmp/github-agent-bridge-dev.sqlite3

gab --db "$DB" init-db
gab --db "$DB" --policy ./policy.example.json enqueue-comment-url \
  'https://github.com/gisce/erp/pull/27675#issuecomment-4419572864'
gab --db "$DB" --policy ./policy.example.json jobs --limit 5
```

Then process it without external side effects:

```bash
gab --db "$DB" --policy ./policy.example.json run --mode shadow --once
```

> Production DBs/policies are operator-owned. Use them only when explicitly asked.

## Safety invariants

| Area | Invariant |
| --- | --- |
| Mailbox | Never enable `--mark-seen` in development fixtures or shadow tests. |
| Scope | `enabledRepos` is a hard canary allowlist when non-empty. |
| Queue | Duplicate `message_id`s must not create duplicate jobs. |
| Concurrency | Active jobs with the same `work_key` must coalesce, not run concurrently. |
| Modes | `shadow` and `dry-run` must not call GitHub or OpenClaw. |
| Secrets | Never commit tokens, app passwords, local DBs, logs, or `~/.config/*`. |

## Where to change things

| Area | Files |
| --- | --- |
| Parser/action detection | `src/github_agent_bridge/parser.py`, `tests/test_parser.py` |
| Policy decisions | `src/github_agent_bridge/policy.py`, `tests/test_policy.py` |
| Queue schema/state | `src/github_agent_bridge/queue.py`, `src/github_agent_bridge/sql/schema.sql`, `tests/test_queue.py` |
| Dispatch/prompt construction | `src/github_agent_bridge/dispatch.py`, `tests/test_modes_cli.py`, `tests/test_prompt_rules.py` |
| Prompt rules | `src/github_agent_bridge/prompt_rules/*.md`, policy `promptOverrides` loader in `src/github_agent_bridge/policy.py` |
| Repository roles | `src/github_agent_bridge/prompt_rules/roles/*.md` |
| CLI behavior | `src/github_agent_bridge/cli.py`, CLI tests |
| Monitoring | `src/github_agent_bridge/monitor.py`, `tests/test_monitor.py` |
| Operator docs | `docs/operations.md`, `docs/shadow-canary.md` |

## Policy gates

Full policy schema and semantics are documented in [`policy-reference.md`](policy-reference.md).

`enabledRepos` is the safest live rollout control:

```json
{
  "trustedOrgs": ["gisce"],
  "enabledRepos": ["gisce/erp"]
}
```

When non-empty, every repo outside the set is denied before trust/action checks.

## Prompt and packaged resources

Prompt resources are packaged with the Python distribution and loaded through `importlib.resources`.

| Resource | Purpose |
| --- | --- |
| `prompt_rules/base.md` | Base GitHub work prompt. |
| `prompt_rules/review_only.md` | Review-only action constraints. |
| `prompt_rules/sync_after_merge.md` | Post-merge workspace cleanup constraints. |
| `prompt_rules/worktree.md` | Worktree behavior. |
| `prompt_rules/pr_metadata.md` | PR metadata behavior. |
| `prompt_rules/human_reviewer.md` | Reviewer-request behavior. |
| `prompt_rules/roles/*.md` | Repository operating postures. |
| `sql/schema.sql` | SQLite schema. |

If you add or rename a packaged resource:

1. update the loader code;
2. update resource tests;
3. update `promptOverrides` documentation if the resource is operator-customizable;
4. build a wheel and verify the file is included.

Operators can customize selected prompt resources through `policy.json` `promptOverrides`. Keep packaged defaults usable on their own; overrides are deployment configuration, not a replacement for sane defaults.

## Role and intent semantics

Role and work intent are separate.

| Concept | Controls | Example |
| --- | --- | --- |
| Repository role | judgment and authority | `owner`, `maintainer`, `contributor`, `reviewer` |
| Work intent | allowed actions | `review_only`, `work_allowed` |

`owner` + `review_only` should preserve owner-level judgment while forbidding code and metadata changes. Do not auto-convert review-only work to the `reviewer` role.

## PR checklist

- [ ] Tests added/updated for changed parser, policy, queue, dispatch, CLI, monitor, or resources.
- [ ] `pytest -q` passes.
- [ ] Wheel/sdist resources checked when packaged files change.
- [ ] Operator-facing changes documented in `docs/operations.md` or `docs/shadow-canary.md`.
- [ ] Policy changes documented in `docs/policy-reference.md`.
- [ ] No secrets, local DBs, app passwords, personal mailbox state, or generated caches committed.
- [ ] Rollback is clear for systemd/config changes.

## Commit messages

Use Conventional Commits so automated releases can infer versions. See [`releases.md`](releases.md).

```text
fix: avoid duplicate jobs for coalesced notifications
feat: add repo-level retry policy
docs: clarify canary rollout
```
