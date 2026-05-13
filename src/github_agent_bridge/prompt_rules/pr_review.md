# PR review rule

This job exists because GitHub requested a review from the bot.

Act through GitHub's Pull Request Review flow, not as a normal issue comment:

- Inspect the PR conceptually, not only syntactically: goal, design fit, correctness, regressions, security, tests, docs, migration/operational impact, and repository conventions.
- Use the configured repository role for judgment. If the role is `maintainer` or `owner`, review with maintainer/owner-level authority; do not downgrade yourself to a passive reviewer.
- Finish with exactly one formal GitHub review verdict:
  - approve when the PR is correct and ready,
  - comment when you have non-blocking concerns, questions, or discussion points,
  - request changes when something is incorrect, unsafe, incoherent, or must be reworked before merge.
- Submit that verdict with `gh pr review` or the GitHub API. Do not leave only a normal PR/issue comment.
- If useful, add inline review comments on the changed lines. Use GitHub review comments/API for inline findings, not separate generic comments.
- The review body must summarize the reasoning and mention what you checked. Avoid shallow “syntax-only” reviews unless the PR itself is truly syntax-only.

Useful commands:

```bash
gh pr review <number> --repo <owner/repo> --approve --body-file <file>
gh pr review <number> --repo <owner/repo> --comment --body-file <file>
gh pr review <number> --repo <owner/repo> --request-changes --body-file <file>
```

For inline comments, use the GitHub API to create a pull request review with `comments` entries containing `path`, `line` or `position`, and `body`.
