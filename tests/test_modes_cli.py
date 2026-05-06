from github_agent_bridge.dispatch import GitHubClient, OpenClawDispatcher, RunMode
from github_agent_bridge.models import GitHubContext, Job
from github_agent_bridge.policy import Policy


def make_job():
    ctx = GitHubContext(["https://github.com/gisce/erp/pull/1#discussion_r2"], "gisce/erp", 1, review_comment_id=2)
    return Job(1, ctx.work_key, ctx.repo, ctx.issue_number, "running", "reply_comment", "work_allowed", "subject", "<x@github.com>", 1, ctx)


def test_shadow_github_reaction_has_no_external_failure():
    assert GitHubClient(gh_bin="definitely-not-present", mode=RunMode.SHADOW).react_eyes(make_job().context) is True


def test_shadow_dispatch_returns_command_without_running():
    result = OpenClawDispatcher(openclaw_bin="definitely-not-present", mode=RunMode.SHADOW).dispatch(make_job(), Policy(trusted_orgs={"gisce"}), reaction_ok=True)
    assert result.ok is True
    assert result.command
    assert "agent" in result.command
