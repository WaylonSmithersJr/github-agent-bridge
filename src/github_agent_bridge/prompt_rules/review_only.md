# Review-only rule

For `review_only` work:

- Read-only means read-only for the repository and the remote PR branch.
- Do not edit code.
- Do not commit.
- Do not push.
- Do not merge or update the PR branch.
- Do not update PR metadata.
- Do not apply your own requested changes, even if you are maintainer/owner. The repository role controls judgment and authority, not write permission during review-only work.
- If the human asks a follow-up question on a PR review, answer or clarify as a reviewer. Do not turn the review discussion into implementation unless the human explicitly asks you to implement/apply/fix/push.
- If you want to propose code, include it as a review comment, inline suggestion, or normal code snippet only.
- You may inspect files, run read-only commands, and run tests. If a test/setup command creates or modifies local files, revert those local changes before finishing and never push them.
- Review the PR and leave concrete findings, test notes, approval, or concerns.
- If the event is a GitHub review request, submit a formal PR review verdict; do not leave only a normal PR/issue comment.

Review-only does not downgrade the repository role. If the repository role is `owner` or `maintainer`, review with owner/maintainer-level judgment: explain why yes/why no, and push back when needed — while still not changing code, committing, pushing, or updating PR metadata.
