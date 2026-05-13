from __future__ import annotations

import json
import os
import re
import signal
import subprocess
from dataclasses import dataclass
from importlib import resources
from enum import StrEnum

from .models import GitHubContext, Job
from .policy import DEFAULT_REPO_ROLE, Policy, Route

PROMPT_RULES_PACKAGE = "github_agent_bridge.prompt_rules"


def load_prompt_rule(name: str) -> str:
    """Read a packaged Markdown prompt rule.

    The rules are package resources so they remain available after wheel/sdist
    installation. Keep them as Markdown files instead of inline strings so
    agents and humans can review/edit them directly.
    """
    return resources.files(PROMPT_RULES_PACKAGE).joinpath(name).read_text(encoding="utf-8").strip() + "\n"


def load_role_prompt(role: str) -> str:
    """Read a packaged Markdown repository-role prompt."""
    return load_prompt_rule(f"roles/{role}.md")


def load_prompt_override(path) -> str:
    """Read a policy-configured prompt override file."""
    return path.read_text(encoding="utf-8").strip() + "\n"


BASE_PROMPT = load_prompt_rule("base.md")
WORKTREE_RULES = load_prompt_rule("worktree.md")
PR_METADATA_RULES = load_prompt_rule("pr_metadata.md")
HUMAN_REVIEWER_RULES = load_prompt_rule("human_reviewer.md")
REVIEW_ONLY_RULES = load_prompt_rule("review_only.md")
SYNC_AFTER_MERGE_RULES = load_prompt_rule("sync_after_merge.md")
PR_REVIEW_RULES = load_prompt_rule("pr_review.md")
COMMENT_VALUE_RULES = load_prompt_rule("comment_value.md")


class RunMode(StrEnum):
    SHADOW = "shadow"  # no external side effects: no GitHub reaction, no OpenClaw dispatch
    DRY_RUN = "dry-run"  # no external side effects, but render intended commands/actions
    LIVE = "live"  # perform GitHub reaction and OpenClaw dispatch


@dataclass(frozen=True)
class DispatchResult:
    ok: bool
    returncode: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    reaction_ok: bool | None = None
    command: list[str] | None = None

    @property
    def detail(self) -> str:
        return (self.stderr or self.stdout or "").replace("\n", " ")[:1000]


class GitHubClient:
    def __init__(self, gh_bin: str = "gh", mode: RunMode = RunMode.LIVE):
        self.mode = mode
        self.gh_bin = gh_bin

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run([self.gh_bin, *args], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def current_login(self) -> str | None:
        result = self._run(["api", "user", "--jq", ".login"])
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None

    def pull_request_review(self, ctx: GitHubContext) -> dict | None:
        if not ctx.repo or not ctx.review_id:
            return None
        result = self._run(["api", f"repos/{ctx.repo}/pulls/{ctx.issue_number}/reviews/{ctx.review_id}"])
        if result.returncode != 0:
            return None
        try:
            return json.loads(result.stdout or "{}")
        except json.JSONDecodeError:
            return None

    def is_non_actionable_review(self, ctx: GitHubContext) -> bool:
        review = self.pull_request_review(ctx)
        if not review:
            return False
        body = (review.get("body") or "").lower()
        non_actionable_markers = (
            "generated no new comments",
            "wasn't able to review any files",
            "was not able to review any files",
            "no actionable comments",
            "no actionable findings",
            "no action required",
            "nothing to change",
        )
        return any(marker in body for marker in non_actionable_markers)

    def is_non_actionable_copilot_review(self, ctx: GitHubContext) -> bool:
        return self.is_non_actionable_review(ctx)

    def issue_comment_body(self, ctx: GitHubContext) -> str | None:
        if not ctx.repo or not ctx.comment_id:
            return None
        result = self._run(["api", f"repos/{ctx.repo}/issues/comments/{ctx.comment_id}", "--jq", ".body"])
        if result.returncode != 0:
            return None
        return result.stdout or ""

    def issue_comment_addresses_current_user(self, ctx: GitHubContext) -> bool:
        body = self.issue_comment_body(ctx)
        login = self.current_login()
        if body is None or not login:
            return False
        mentions = [m.lower() for m in re.findall(r"@([A-Za-z0-9-]+)", body)]
        if not mentions:
            return False
        # Treat the comment as addressed to the bot only when the bot is the
        # first mentioned user. A later mention can be merely referential, e.g.
        # "@Marc what do you think about @pilipilisbot's changes?"
        return mentions[0] == login.lower()

    def issue_comment_mentions_current_user(self, ctx: GitHubContext) -> bool:
        return self.issue_comment_addresses_current_user(ctx)

    def react(self, ctx: GitHubContext, content: str) -> bool:
        if self.mode != RunMode.LIVE:
            return True
        repo, issue = ctx.repo, ctx.issue_number
        if not repo or not issue:
            return False
        if ctx.comment_id:
            return self._run(["api", "-X", "POST", f"repos/{repo}/issues/comments/{ctx.comment_id}/reactions", "-f", f"content={content}", "-H", "Accept: application/vnd.github+json"]).returncode == 0
        if ctx.review_comment_id:
            return self._run(["api", "-X", "POST", f"repos/{repo}/pulls/comments/{ctx.review_comment_id}/reactions", "-f", f"content={content}", "-H", "Accept: application/vnd.github+json"]).returncode == 0
        return self._run(["api", "-X", "POST", f"repos/{repo}/issues/{issue}/reactions", "-f", f"content={content}", "-H", "Accept: application/vnd.github+json"]).returncode == 0

    def is_assigned_to_current_user(self, ctx: GitHubContext) -> bool:
        repo, issue = ctx.repo, ctx.issue_number
        if not repo or not issue:
            return False
        login = self.current_login()
        if not login:
            return False
        result = self._run(["api", f"repos/{repo}/issues/{issue}"])
        if result.returncode != 0:
            return False
        try:
            data = json.loads(result.stdout or "{}")
        except json.JSONDecodeError:
            return False
        return login in {a.get("login") for a in data.get("assignees", []) if isinstance(a, dict)}

    def react_eyes(self, ctx: GitHubContext) -> bool:
        return self.react(ctx, "eyes")

    def react_ack_no_comment(self, ctx: GitHubContext) -> bool:
        return self.react(ctx, "+1")


class OpenClawDispatcher:
    def __init__(
        self,
        openclaw_bin: str = "openclaw",
        node_bin: str | None = None,
        default_channel: str = "telegram",
        default_to: str = "",
        timeout_seconds: int = 3600,
        mode: RunMode = RunMode.LIVE,
        review_timeout_seconds: int = 900,
        work_timeout_seconds: int = 3600,
        cli_grace_seconds: int = 60,
    ):
        self.openclaw_bin = openclaw_bin
        self.node_bin = node_bin
        self.default_channel = default_channel
        self.default_to = default_to
        self.timeout_seconds = timeout_seconds
        self.review_timeout_seconds = review_timeout_seconds
        self.work_timeout_seconds = work_timeout_seconds
        self.cli_grace_seconds = cli_grace_seconds
        self.mode = mode

    def timeout_for(self, job: Job) -> int:
        if job.work_intent == "review_only":
            return self.review_timeout_seconds
        if job.work_intent == "work_allowed":
            return self.work_timeout_seconds
        return self.timeout_seconds

    def build_prompt(self, job: Job, policy: Policy | None = None) -> str:
        repo = job.repo or "unknown/repo"; thread = job.thread or 0
        role = policy.role_for(job.repo) if policy else DEFAULT_REPO_ROLE
        role_override = policy.prompt_overrides.role_path(role) if policy else None
        intent_override = policy.prompt_overrides.intent_path(job.work_intent) if policy else None
        base_template = load_prompt_override(policy.prompt_overrides.base) if policy and policy.prompt_overrides.base else BASE_PROMPT
        role_prompt = load_prompt_override(role_override) if role_override else load_role_prompt(role)
        intent_rules = ""
        if job.work_intent == "review_only":
            intent_rules = load_prompt_override(intent_override) if intent_override else REVIEW_ONLY_RULES
        action_rules = ""
        if job.action == "sync_after_merge":
            action_rules = SYNC_AFTER_MERGE_RULES
        elif job.action == "submit_review":
            action_rules = PR_REVIEW_RULES
        base_prompt = base_template.format(
            repo=repo,
            thread=thread,
            action=job.action,
            work_intent=job.work_intent,
            url=job.context.short_url,
            message_id=job.message_id,
            subject=job.subject,
        )
        return f"{base_prompt}{role_prompt}{intent_rules}{action_rules}{COMMENT_VALUE_RULES}{WORKTREE_RULES}{PR_METADATA_RULES}{HUMAN_REVIEWER_RULES}"

    def route_for(self, job: Job, policy: Policy) -> tuple[str | None, str, str]:
        route: Route = policy.route_for(job.repo)
        agent = route.agent
        channel = route.channel or self.default_channel
        to = route.to or self.default_to
        return agent, channel, to

    def dispatch(self, job: Job, policy: Policy, reaction_ok: bool | None = None) -> DispatchResult:
        agent, channel, to = self.route_for(job, policy)
        cmd = [self.openclaw_bin, "agent"]
        if agent:
            cmd += ["--agent", agent]
        agent_timeout = self.timeout_for(job)
        cmd += ["--channel", channel, "--to", to, "--deliver", "--timeout", str(agent_timeout), "--message", self.build_prompt(job, policy)]
        env = os.environ.copy()
        if self.node_bin:
            env["PATH"] = os.path.dirname(self.node_bin) + os.pathsep + env.get("PATH", "")
        if self.mode != RunMode.LIVE:
            return DispatchResult(True, 0, "side effects skipped", "", False, reaction_ok, cmd)
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env, start_new_session=True)
        try:
            # Let OpenClaw's own --timeout own the agent run deadline. The bridge only
            # keeps a small grace window so it can capture the CLI result cleanly.
            out, err = proc.communicate(timeout=agent_timeout + self.cli_grace_seconds)
            return DispatchResult(proc.returncode == 0, proc.returncode, (out or "")[:2000], (err or "")[:4000], False, reaction_ok, cmd)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except Exception:
                proc.kill()
            out, err = proc.communicate()
            return DispatchResult(False, 124, (out or "")[:2000], (err or "")[:4000], True, reaction_ok, cmd)
