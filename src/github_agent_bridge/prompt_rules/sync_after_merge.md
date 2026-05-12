# Sync-after-merge rule

This PR appears to have been merged.

Perform post-merge workspace cleanup:

- Resolve the dedicated PR worktree using the agent/repo workspace conventions.
- If a dedicated worktree exists and is clean, remove it.
- If it is dirty or has untracked changes, do not remove it; report the path and reason.
- Do not remove the canonical repository checkout.
- If no worktree exists, report that there is nothing to clean.
- If later work arrives for the same PR, recreate the worktree from the canonical repository checkout as needed.
