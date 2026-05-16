from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .models import GitHubContext, Notification

ALLOWED_REPO_ROLES = {"owner", "maintainer", "contributor", "reviewer"}
ALLOWED_PROMPT_INTENTS = {"review_only"}
DEFAULT_REPO_ROLE = "contributor"


@dataclass(frozen=True)
class Route:
    agent: str | None = None
    channel: str | None = None
    to: str | None = None


@dataclass(frozen=True)
class PromptOverrides:
    base: Path | None = None
    roles: dict[str, Path] = field(default_factory=dict)
    intents: dict[str, Path] = field(default_factory=dict)

    def role_path(self, role: str) -> Path | None:
        return self.roles.get(role.lower())

    def intent_path(self, intent: str) -> Path | None:
        return self.intents.get(intent.lower())


@dataclass(frozen=True)
class FeedbackLearning:
    enabled: bool = True
    min_confidence: float = 0.5


@dataclass(frozen=True)
class Policy:
    source_from: str = "notifications@github.com"
    required_url_prefix: str = "https://github.com/"
    message_id_domain: str = "github.com"
    trusted_repos: set[str] = field(default_factory=set)
    trusted_orgs: set[str] = field(default_factory=set)
    enabled_repos: set[str] = field(default_factory=set)
    auto_actions: set[str] = field(default_factory=lambda: {"archive_notification"})
    ask_actions: set[str] = field(default_factory=lambda: {"reply_comment", "open_issue", "docs_update", "content_change"})
    trusted_auto_actions: set[str] = field(default_factory=lambda: {"reply_comment", "open_issue", "submit_review", "sync_after_merge"})
    repo_routes: dict[str, Route] = field(default_factory=dict)
    org_routes: dict[str, Route] = field(default_factory=dict)
    repo_roles: dict[str, str] = field(default_factory=dict)
    org_roles: dict[str, str] = field(default_factory=dict)
    prompt_overrides: PromptOverrides = field(default_factory=PromptOverrides)
    feedback_learning: FeedbackLearning = field(default_factory=FeedbackLearning)

    @classmethod
    def from_file(cls, path: str | Path) -> "Policy":
        policy_path = Path(path).expanduser()
        data = json.loads(policy_path.read_text(encoding="utf-8"))
        source = data.get("source", {}); actions = data.get("actions", {})

        def routes(raw: dict) -> dict[str, Route]:
            return {k.lower(): Route(**v) for k, v in (raw or {}).items() if isinstance(v, dict)}

        def roles(raw: dict) -> dict[str, str]:
            result = {k.lower(): str(v).lower() for k, v in (raw or {}).items()}
            unknown = sorted(set(result.values()) - ALLOWED_REPO_ROLES)
            if unknown:
                raise ValueError(f"unknown repo role(s): {unknown}; allowed roles: {sorted(ALLOWED_REPO_ROLES)}")
            return result

        def prompt_path(raw_path: str) -> Path:
            candidate = Path(raw_path).expanduser()
            if not candidate.is_absolute():
                candidate = policy_path.parent / candidate
            if not candidate.is_file():
                raise ValueError(f"prompt override file does not exist: {candidate}")
            if not candidate.read_text(encoding="utf-8").strip():
                raise ValueError(f"prompt override file is empty: {candidate}")
            return candidate

        def prompt_overrides(raw: dict) -> PromptOverrides:
            raw = raw or {}
            base = prompt_path(raw["base"]) if raw.get("base") else None
            raw_roles = raw.get("roles", {}) or {}
            role_names = {str(k).lower() for k in raw_roles}
            unknown_roles = sorted(role_names - ALLOWED_REPO_ROLES)
            if unknown_roles:
                raise ValueError(f"unknown prompt override role(s): {unknown_roles}; allowed roles: {sorted(ALLOWED_REPO_ROLES)}")
            raw_intents = raw.get("intents", {}) or {}
            intent_names = {str(k).lower() for k in raw_intents}
            unknown_intents = sorted(intent_names - ALLOWED_PROMPT_INTENTS)
            if unknown_intents:
                raise ValueError(f"unknown prompt override intent(s): {unknown_intents}; allowed intents: {sorted(ALLOWED_PROMPT_INTENTS)}")
            return PromptOverrides(
                base=base,
                roles={str(k).lower(): prompt_path(v) for k, v in raw_roles.items()},
                intents={str(k).lower(): prompt_path(v) for k, v in raw_intents.items()},
            )

        def feedback_learning(raw: dict) -> FeedbackLearning:
            raw = raw or {}
            min_confidence = float(raw.get("minConfidence", 0.5))
            if min_confidence < 0 or min_confidence > 1:
                raise ValueError("feedbackLearning.minConfidence must be between 0 and 1")
            return FeedbackLearning(enabled=bool(raw.get("enabled", True)), min_confidence=min_confidence)

        return cls(
            source_from=source.get("from", cls.source_from),
            required_url_prefix=source.get("requiredUrlPrefix", cls.required_url_prefix),
            message_id_domain=source.get("messageIdDomain", cls.message_id_domain),
            trusted_repos={r.lower() for r in data.get("trustedRepos", [])},
            trusted_orgs={o.lower() for o in data.get("trustedOrgs", [])},
            enabled_repos={r.lower() for r in data.get("enabledRepos", [])},
            auto_actions=set(actions.get("auto", ["archive_notification"])),
            ask_actions=set(actions.get("ask", ["reply_comment", "open_issue", "docs_update", "content_change"])),
            trusted_auto_actions=set(actions.get("trustedAuto", ["reply_comment", "open_issue", "submit_review", "sync_after_merge"])),
            repo_routes=routes(data.get("repoRoutes", {})), org_routes=routes(data.get("orgRoutes", {})),
            repo_roles=roles(data.get("repoRoles", {})), org_roles=roles(data.get("orgRoles", {})),
            prompt_overrides=prompt_overrides(data.get("promptOverrides", {})),
            feedback_learning=feedback_learning(data.get("feedbackLearning", {})),
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
        if self.enabled_repos and (ctx.repo or "").lower() not in self.enabled_repos:
            return "deny"
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

    def role_for(self, repo: str | None) -> str:
        repo = (repo or "").lower(); org = repo.split("/", 1)[0] if "/" in repo else ""
        return self.repo_roles.get(repo) or self.org_roles.get(org) or DEFAULT_REPO_ROLE
