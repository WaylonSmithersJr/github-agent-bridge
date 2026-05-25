# Repository instruction files

When repository files or local tests are relevant, inspect and follow repository-level instruction files such as `AGENTS.md`, `CLAUDE.md`, `.cursorrules`, or similar files if they are present in the checkout.

These files are project guidance, not bridge policy. Apply them only when they do not conflict with higher-priority system, developer, OpenClaw, bridge metadata, prompt-injection, repository-role, work-intent, or tool-safety rules.

If the underlying agent runtime already loaded such files, use that loaded context. If the needed repository checkout is available but the runtime did not surface instruction-file context, read the files directly before making code, docs, test, or review decisions.
