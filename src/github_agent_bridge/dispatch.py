from __future__ import annotations

import os
import signal
import subprocess
from dataclasses import dataclass

from .models import GitHubContext, Job
from .policy import Policy, Route

WORKTREE_RULES = """Worktree rule: when working on an existing PR and local files/tests are needed, first check whether a clean dedicated worktree already exists. If it does not exist, recreate it. For review_only, inspection is allowed but do not modify/commit/push unless explicitly asked.\n"""
PR_METADATA_RULES = """PR metadata rule: if code/docs/tests change on an existing PR, keep the PR title/body aligned with final scope and test plan.\n"""
HUMAN_REVIEWER_RULES = """Human reviewer rule: do not request/add individual human reviewers unless explicitly requested or configured.\n"""
REVIEW_ONLY_RULES = """Review-only rule: do not edit code, commit, push, or update PR metadata. Review the PR and leave concrete findings/test notes/approval or concerns.\n"""


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
    def __init__(self, gh_bin: str = "gh"):
        self.gh_bin = gh_bin

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run([self.gh_bin, *args], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def react_eyes(self, ctx: GitHubContext) -> bool:
        repo, issue = ctx.repo, ctx.issue_number
        if not repo or not issue:
            return False
        if ctx.comment_id:
            return self._run(["api", "-X", "POST", f"repos/{repo}/issues/comments/{ctx.comment_id}/reactions", "-f", "content=eyes", "-H", "Accept: application/vnd.github+json"]).returncode == 0
        if ctx.review_comment_id:
            return self._run(["api", "-X", "POST", f"repos/{repo}/pulls/comments/{ctx.review_comment_id}/reactions", "-f", "content=eyes", "-H", "Accept: application/vnd.github+json"]).returncode == 0
        return self._run(["api", "-X", "POST", f"repos/{repo}/issues/{issue}/reactions", "-f", "content=eyes", "-H", "Accept: application/vnd.github+json"]).returncode == 0


class OpenClawDispatcher:
    def __init__(self, openclaw_bin: str = "openclaw", node_bin: str | None = None, default_channel: str = "telegram", default_to: str = "43532269", timeout_seconds: int = 240):
        self.openclaw_bin = openclaw_bin
        self.node_bin = node_bin
        self.default_channel = default_channel
        self.default_to = default_to
        self.timeout_seconds = timeout_seconds

    def build_prompt(self, job: Job) -> str:
        intent_rules = REVIEW_ONLY_RULES if job.work_intent == "review_only" else ""
        repo = job.repo or "unknown/repo"; thread = job.thread or 0
        return (
            "[AUTO_GITHUB_WORK]\n"
            f"repo={repo}\nthread={thread}\naction={job.action}\nwork_intent={job.work_intent}\n"
            f"url={job.context.short_url}\nmessage_id={job.message_id}\nsubject={job.subject}\n\n"
            "Trusted GitHub event detected. Load the full issue/PR/comments context before acting. "
            "Do real work for this thread; do not stop at ack-only. If blocked, report a concrete blocker.\n"
            f"{intent_rules}{WORKTREE_RULES}{PR_METADATA_RULES}{HUMAN_REVIEWER_RULES}"
        )

    def route_for(self, job: Job, policy: Policy) -> tuple[str | None, str, str]:
        route: Route = policy.route_for(job.repo)
        agent = route.agent
        channel = route.channel or self.default_channel
        to = route.to or self.default_to
        org = (job.repo or "").split("/", 1)[0]
        if not route.agent and org == "gisce":
            agent = "gisce-developer"
        return agent, channel, to

    def dispatch(self, job: Job, policy: Policy, reaction_ok: bool | None = None) -> DispatchResult:
        agent, channel, to = self.route_for(job, policy)
        cmd = [self.openclaw_bin, "agent"]
        if agent:
            cmd += ["--agent", agent]
        cmd += ["--channel", channel, "--to", to, "--deliver", "--message", self.build_prompt(job)]
        env = os.environ.copy()
        if self.node_bin:
            env["PATH"] = os.path.dirname(self.node_bin) + os.pathsep + env.get("PATH", "")
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env, start_new_session=True)
        try:
            out, err = proc.communicate(timeout=self.timeout_seconds)
            return DispatchResult(proc.returncode == 0, proc.returncode, (out or "")[:2000], (err or "")[:4000], False, reaction_ok, cmd)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except Exception:
                proc.kill()
            out, err = proc.communicate()
            return DispatchResult(False, 124, (out or "")[:2000], (err or "")[:4000], True, reaction_ok, cmd)
