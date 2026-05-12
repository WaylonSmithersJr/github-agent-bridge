# Development workflow

This guide is for agents and humans changing the bridge.

## Local setup

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
pytest -q
```

## Safe manual replay of a GitHub comment

Use `enqueue-comment-url` instead of hand-writing notification JSON:

```bash
DB=/tmp/github-agent-bridge-dev.sqlite3
gab --db "$DB" init-db
gab --db "$DB" --policy ./policy.example.json enqueue-comment-url \
  'https://github.com/gisce/erp/pull/27675#issuecomment-4419572864'
gab --db "$DB" --policy ./policy.example.json jobs --limit 5
```

Then process it without side effects:

```bash
gab --db "$DB" --policy ./policy.example.json run --mode shadow --once
```

To process in production, only use the configured production DB/policy when explicitly asked by the operator.

## Policy gates

Full policy schema and semantics are documented in `docs/policy-reference.md`.


`enabledRepos` is a hard canary allowlist. When non-empty, every repo outside the set is denied before trust/action checks. This lets the operator move one repo from the legacy worker to this bridge without widening live scope.

Example:

```json
{
  "trustedOrgs": ["gisce"],
  "enabledRepos": ["gisce/erp"]
}
```

## PR checklist

- [ ] Added/updated tests for changed parser, policy, queue, dispatch, CLI or monitor behavior.
- [ ] `pytest -q` passes.
- [ ] New operational commands are documented here or in `docs/operations.md`.
- [ ] No secrets, local DBs, app passwords or personal mailbox state committed.
- [ ] Rollback is clear for systemd/config changes.

## Prompt rules

Agent prompt rules live in `src/github_agent_bridge/prompt_rules/*.md`. Repository-role prompts live in `src/github_agent_bridge/prompt_rules/roles/*.md`. They are packaged resources loaded with `importlib.resources`, not external runtime files. If you add or rename a rule file, update `dispatch.py` and `tests/test_prompt_rules.py`, then verify the wheel contains the Markdown files.

SQLite schema lives in `src/github_agent_bridge/sql/schema.sql` and is packaged with the project. If schema changes, update queue tests and verify wheel contents.

Avoid adding organization-specific routing fallbacks in code. Put repo/org routing in `policy.example.json` or the deployed policy file.

## Commit messages

Use Conventional Commits so automated releases can infer versions. See `docs/releases.md`.

Repository roles are configured through `repoRoles` and `orgRoles` in policy files. Keep role behavior in Markdown resources, not inline Python strings.
