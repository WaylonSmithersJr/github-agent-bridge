from github_agent_bridge.dispatch import GitHubClient, OpenClawDispatcher, RunMode
from github_agent_bridge.models import GitHubContext, Job
from github_agent_bridge.policy import Policy


def make_job(work_intent="work_allowed"):
    ctx = GitHubContext(["https://github.com/gisce/erp/pull/1#discussion_r2"], "gisce/erp", 1, review_comment_id=2)
    return Job(1, ctx.work_key, ctx.repo, ctx.issue_number, "running", "reply_comment", work_intent, "subject", "<x@github.com>", 1, ctx)


def test_shadow_github_reaction_has_no_external_failure():
    assert GitHubClient(gh_bin="definitely-not-present", mode=RunMode.SHADOW).react_eyes(make_job().context) is True


class RecordingGitHubClient(GitHubClient):
    def __init__(self):
        super().__init__(mode=RunMode.LIVE)
        self.calls = []

    def _run(self, args):
        self.calls.append(args)

        class Result:
            returncode = 0
            stdout = '[{"id": 123}, {"id": 456}]' if args[-1].endswith("/comments") else "{}"
            stderr = ""

        return Result()


def test_review_reaction_targets_review_comments():
    client = RecordingGitHubClient()
    ctx = GitHubContext(
        ["https://github.com/gisce/erp/pull/1#pullrequestreview-99"],
        "gisce/erp",
        1,
        review_id=99,
        target_kind="review",
    )

    assert client.react_eyes(ctx) is True

    assert any(call[-1].endswith("/reviews/99/comments") for call in client.calls)
    assert any("pulls/comments/123/reactions" in " ".join(call) for call in client.calls)
    assert any("pulls/comments/456/reactions" in " ".join(call) for call in client.calls)


def test_commit_comment_reaction_targets_commit_comment():
    client = RecordingGitHubClient()
    ctx = GitHubContext(
        ["https://github.com/pilipilisbot/github-agent-bridge/commit/fbd7bc1#r185806568"],
        "pilipilisbot/github-agent-bridge",
        commit_comment_id=185806568,
        commit_sha="fbd7bc1",
        target_kind="commit_comment",
    )

    assert client.react_eyes(ctx) is True

    assert any("repos/pilipilisbot/github-agent-bridge/comments/185806568/reactions" in " ".join(call) for call in client.calls)


def test_shadow_dispatch_returns_command_without_running():
    result = OpenClawDispatcher(openclaw_bin="definitely-not-present", mode=RunMode.SHADOW).dispatch(make_job(), Policy(trusted_orgs={"gisce"}), reaction_ok=True)
    assert result.ok is True
    assert result.command
    assert "agent" in result.command
    assert "--timeout" in result.command
    assert "3600" in result.command


def test_review_only_dispatch_uses_shorter_timeout():
    dispatcher = OpenClawDispatcher(openclaw_bin="definitely-not-present", mode=RunMode.SHADOW)
    result = dispatcher.dispatch(make_job("review_only"), Policy(trusted_orgs={"gisce"}), reaction_ok=True)
    assert result.command
    timeout_idx = result.command.index("--timeout")
    assert result.command[timeout_idx + 1] == "900"


def test_dispatcher_does_not_hardcode_org_agent_fallback():
    dispatcher = OpenClawDispatcher(mode=RunMode.SHADOW)
    job = make_job()
    assert dispatcher.route_for(job, Policy()) == (None, "telegram", "")


def test_dispatch_passes_policy_role_into_prompt():
    result = OpenClawDispatcher(openclaw_bin="definitely-not-present", mode=RunMode.SHADOW).dispatch(
        make_job(), Policy(repo_roles={"gisce/erp": "owner"}), reaction_ok=True
    )
    assert result.command
    message = result.command[result.command.index("--message") + 1]
    assert "# Repository role: owner" in message
