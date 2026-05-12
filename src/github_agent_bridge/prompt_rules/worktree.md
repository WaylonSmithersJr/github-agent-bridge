# Worktree rule

When working on an existing PR and local files or tests are needed:

- First check whether a clean dedicated worktree already exists.
- If it does not exist, recreate it.
- For `review_only` work, creating/checking out a worktree is allowed only for inspection/tests.
- For `review_only` work, do not modify files, commit, or push unless explicitly asked.
