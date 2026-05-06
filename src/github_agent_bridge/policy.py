from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .models import GitHubContext, Notification


@dataclass(frozen=True)
class Route:
    agent: str | None = None
    channel: str | None = None
    to: str | None = None


@dataclass(frozen=True)
class Policy:
    source_from: str = "notifications@github.com"
    required_url_prefix: str = "https://github.com/"
    message_id_domain: str = "github.com"
    trusted_repos: set[str] = field(default_factory=set)
    trusted_orgs: set[str] = field(default_factory=set)
    auto_actions: set[str] = field(default_factory=lambda: {"archive_notification", "sync_after_merge"})
    ask_actions: set[str] = field(default_factory=lambda: {"reply_comment", "open_issue", "docs_update", "content_change"})
    trusted_auto_actions: set[str] = field(default_factory=lambda: {"reply_comment", "open_issue"})
    repo_routes: dict[str, Route] = field(default_factory=dict)
    org_routes: dict[str, Route] = field(default_factory=dict)

    @classmethod
    def from_file(cls, path: str | Path) -> "Policy":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        source = data.get("source", {}); actions = data.get("actions", {})
        def routes(raw: dict) -> dict[str, Route]:
            return {k.lower(): Route(**v) for k, v in (raw or {}).items() if isinstance(v, dict)}
        return cls(
            source_from=source.get("from", cls.source_from),
            required_url_prefix=source.get("requiredUrlPrefix", cls.required_url_prefix),
            message_id_domain=source.get("messageIdDomain", cls.message_id_domain),
            trusted_repos={r.lower() for r in data.get("trustedRepos", [])},
            trusted_orgs={o.lower() for o in data.get("trustedOrgs", [])},
            auto_actions=set(actions.get("auto", ["archive_notification", "sync_after_merge"])),
            ask_actions=set(actions.get("ask", ["reply_comment", "open_issue", "docs_update", "content_change"])),
            trusted_auto_actions=set(actions.get("trustedAuto", ["reply_comment", "open_issue"])),
            repo_routes=routes(data.get("repoRoutes", {})), org_routes=routes(data.get("orgRoutes", {})),
        )

    def trusted_source(self, n: Notification, ctx: GitHubContext) -> bool:
        auth_ok = all(bool(n.auth.get(k)) for k in ("spf", "dkim", "dmarc")) if n.auth else True
        return self.source_from in n.from_addr and auth_ok and any(u.startswith(self.required_url_prefix) for u in ctx.urls) and self.message_id_domain in n.message_id

    def repo_trusted(self, repo: str | None) -> bool:
        if not repo:
            return False
        repo = repo.lower(); org = repo.split("/", 1)[0]
        return repo in self.trusted_repos or org in self.trusted_orgs

    def decision(self, n: Notification, ctx: GitHubContext, action: str) -> str:
        if not self.trusted_source(n, ctx):
            return "deny"
        if action in self.auto_actions:
            return "auto"
        if action in self.trusted_auto_actions:
            return "auto_trusted" if self.repo_trusted(ctx.repo) else "ask"
        if action in self.ask_actions:
            return "ask"
        return "deny"

    def route_for(self, repo: str | None) -> Route:
        repo = (repo or "").lower(); org = repo.split("/", 1)[0] if "/" in repo else ""
        return self.repo_routes.get(repo) or self.org_routes.get(org) or Route()
