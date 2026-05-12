from importlib import resources

from github_agent_bridge.dispatch import OpenClawDispatcher, REVIEW_ONLY_RULES, WORKTREE_RULES
from github_agent_bridge.models import GitHubContext, Job
from github_agent_bridge.policy import Policy


def make_job(work_intent="work_allowed"):
    ctx = GitHubContext(["https://github.com/gisce/erp/pull/1#issuecomment-2"], "gisce/erp", 1, comment_id=2)
    return Job(1, ctx.work_key, ctx.repo, ctx.issue_number, "running", "reply_comment", work_intent, "subject", "<x@github.com>", 1, ctx)


def test_prompt_rule_markdown_files_are_packaged_resources():
    package = resources.files("github_agent_bridge.prompt_rules")
    expected = {"base.md", "worktree.md", "pr_metadata.md", "human_reviewer.md", "review_only.md"}
    found = {p.name for p in package.iterdir() if p.name.endswith(".md")}
    assert expected <= found
    for name in expected:
        text = package.joinpath(name).read_text(encoding="utf-8")
        assert text.strip()
        if name != "base.md":
            assert text.startswith("# ")
        assert len(text.strip()) > 40


def test_build_prompt_reads_packaged_markdown_rules():
    prompt = OpenClawDispatcher(mode="shadow").build_prompt(make_job("review_only"))
    assert "[AUTO_GITHUB_WORK]" in prompt
    assert "Trusted GitHub event detected" in prompt
    assert "# Worktree rule" in prompt
    assert "# PR metadata rule" in prompt
    assert "# Human reviewer rule" in prompt
    assert "# Review-only rule" in prompt
    assert WORKTREE_RULES in prompt
    assert REVIEW_ONLY_RULES in prompt
