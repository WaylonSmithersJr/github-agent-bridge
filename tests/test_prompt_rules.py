from dataclasses import replace
from importlib import resources

from github_agent_bridge.dispatch import OpenClawDispatcher, REVIEW_ONLY_RULES, WORKTREE_RULES
from github_agent_bridge.models import GitHubContext, Job
from github_agent_bridge.policy import Policy


def make_job(work_intent="work_allowed"):
    ctx = GitHubContext(["https://github.com/gisce/erp/pull/1#issuecomment-2"], "gisce/erp", 1, comment_id=2)
    return Job(1, ctx.work_key, ctx.repo, ctx.issue_number, "running", "reply_comment", work_intent, "subject", "<x@github.com>", 1, ctx)


def test_prompt_rule_markdown_files_are_packaged_resources():
    package = resources.files("github_agent_bridge.prompt_rules")
    expected = {"base.md", "worktree.md", "pr_metadata.md", "human_reviewer.md", "review_only.md", "sync_after_merge.md"}
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


def test_role_prompt_markdown_files_are_packaged_resources():
    package = resources.files("github_agent_bridge.prompt_rules").joinpath("roles")
    expected = {"owner.md", "maintainer.md", "contributor.md", "reviewer.md"}
    found = {p.name for p in package.iterdir() if p.name.endswith(".md")}
    assert expected <= found
    for name in expected:
        text = package.joinpath(name).read_text(encoding="utf-8")
        assert text.startswith("# Repository role:")
        assert len(text.strip()) > 120


def test_build_prompt_includes_policy_role():
    prompt = OpenClawDispatcher(mode="shadow").build_prompt(make_job(), Policy(repo_roles={"gisce/erp": "owner"}))
    assert "# Repository role: owner" in prompt
    assert "not as an obedient executor" in prompt

    default_prompt = OpenClawDispatcher(mode="shadow").build_prompt(make_job())
    assert "# Repository role: contributor" in default_prompt


def test_review_only_preserves_repository_role_judgment():
    prompt = OpenClawDispatcher(mode="shadow").build_prompt(make_job("review_only"), Policy(repo_roles={"gisce/erp": "owner"}))
    assert "# Repository role: owner" in prompt
    assert "# Review-only rule" in prompt
    assert "does not downgrade the repository role" in prompt
    assert "owner` + `review_only`" in prompt


def test_build_prompt_uses_policy_prompt_overrides(tmp_path):
    base = tmp_path / "base.md"
    owner = tmp_path / "owner.md"
    review_only = tmp_path / "review_only.md"
    base.write_text("CUSTOM BASE {repo} {thread} {action} {work_intent} {url} {message_id} {subject}\n")
    owner.write_text("# Custom owner role\nBe ownerish.\n")
    review_only.write_text("# Custom review-only intent\nNo writes.\n")
    policy_file = tmp_path / "policy.json"
    policy_file.write_text(
        """{
          "repoRoles": {"gisce/erp": "owner"},
          "promptOverrides": {
            "base": "base.md",
            "roles": {"owner": "owner.md"},
            "intents": {"review_only": "review_only.md"}
          }
        }"""
    )
    policy = Policy.from_file(policy_file)

    prompt = OpenClawDispatcher(mode="shadow").build_prompt(make_job("review_only"), policy)

    assert "CUSTOM BASE gisce/erp 1 reply_comment review_only" in prompt
    assert "# Custom owner role" in prompt
    assert "# Custom review-only intent" in prompt
    assert "# Repository role: owner" not in prompt
    assert "# Review-only rule" not in prompt
    assert "# Worktree rule" in prompt
    assert "# PR metadata rule" in prompt
    assert "# Human reviewer rule" in prompt


def test_sync_after_merge_prompt_includes_cleanup_rule():
    job = replace(make_job(), action="sync_after_merge")
    prompt = OpenClawDispatcher(mode="shadow").build_prompt(job, Policy(repo_roles={"gisce/erp": "owner"}))

    assert "# Sync-after-merge rule" in prompt
    assert "Perform post-merge workspace cleanup" in prompt
    assert "If a dedicated worktree exists and is clean, remove it." in prompt
    assert "Do not remove the canonical repository checkout." in prompt


def test_non_merge_prompt_does_not_include_cleanup_rule():
    prompt = OpenClawDispatcher(mode="shadow").build_prompt(make_job(), Policy())
    assert "# Sync-after-merge rule" not in prompt
