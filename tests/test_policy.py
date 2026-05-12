from github_agent_bridge.models import Notification
from github_agent_bridge.parser import extract_github_context
from github_agent_bridge.policy import Policy


def test_trusted_org_auto_trusted():
    body = "@pilipilisbot https://github.com/gisce/erp/issues/1#issuecomment-1"
    n = Notification(1, "<x@github.com>", "subj", "notifications@github.com", body, auth={"spf": True, "dkim": True, "dmarc": True})
    ctx = extract_github_context(body)
    assert Policy(trusted_orgs={"gisce"}).decision(n, ctx, "reply_comment") == "auto_trusted"


def test_enabled_repos_restricts_canary_scope():
    n = Notification(1, "<x@github.com>", "subj", "notifications@github.com", "", auth={"spf": True, "dkim": True, "dmarc": True})
    erp = extract_github_context("@pilipilisbot https://github.com/gisce/erp/issues/1#issuecomment-1")
    other = extract_github_context("@pilipilisbot https://github.com/gisce/other/issues/1#issuecomment-1")
    policy = Policy(trusted_orgs={"gisce"}, enabled_repos={"gisce/erp"})

    assert policy.decision(n, erp, "reply_comment") == "auto_trusted"
    assert policy.decision(n, other, "reply_comment") == "deny"
    assert policy.decision(n, other, "sync_after_merge") == "deny"


def test_repo_roles_precedence_and_default():
    policy = Policy(repo_roles={"gisce/erp": "owner"}, org_roles={"gisce": "maintainer"})

    assert policy.role_for("gisce/erp") == "owner"
    assert policy.role_for("gisce/other") == "maintainer"
    assert policy.role_for("other/repo") == "contributor"


def test_policy_from_file_loads_roles_and_rejects_unknown(tmp_path):
    valid = tmp_path / "policy.json"
    valid.write_text('{"repoRoles": {"GISCE/ERP": "Owner"}, "orgRoles": {"pilipilisbot": "maintainer"}}')
    policy = Policy.from_file(valid)
    assert policy.role_for("gisce/erp") == "owner"
    assert policy.role_for("pilipilisbot/github-agent-bridge") == "maintainer"

    invalid = tmp_path / "invalid.json"
    invalid.write_text('{"repoRoles": {"gisce/erp": "boss"}}')
    try:
        Policy.from_file(invalid)
    except ValueError as exc:
        assert "unknown repo role" in str(exc)
    else:
        raise AssertionError("expected ValueError for unknown repo role")


def test_policy_from_file_loads_prompt_overrides_relative_to_policy(tmp_path):
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "base.md").write_text("custom base {repo}\n")
    (prompts / "owner.md").write_text("custom owner\n")
    (prompts / "review_only.md").write_text("custom review only\n")
    policy_file = tmp_path / "policy.json"
    policy_file.write_text(
        """{
          "promptOverrides": {
            "base": "prompts/base.md",
            "roles": {"owner": "prompts/owner.md"},
            "intents": {"review_only": "prompts/review_only.md"}
          }
        }"""
    )

    policy = Policy.from_file(policy_file)

    assert policy.prompt_overrides.base == prompts / "base.md"
    assert policy.prompt_overrides.role_path("OWNER") == prompts / "owner.md"
    assert policy.prompt_overrides.intent_path("review_only") == prompts / "review_only.md"


def test_policy_from_file_rejects_invalid_prompt_overrides(tmp_path):
    missing = tmp_path / "missing.json"
    missing.write_text('{"promptOverrides": {"base": "nope.md"}}')
    try:
        Policy.from_file(missing)
    except ValueError as exc:
        assert "prompt override file does not exist" in str(exc)
    else:
        raise AssertionError("expected ValueError for missing prompt override")

    prompt = tmp_path / "prompt.md"
    prompt.write_text("content")
    unknown_role = tmp_path / "unknown-role.json"
    unknown_role.write_text('{"promptOverrides": {"roles": {"boss": "prompt.md"}}}')
    try:
        Policy.from_file(unknown_role)
    except ValueError as exc:
        assert "unknown prompt override role" in str(exc)
    else:
        raise AssertionError("expected ValueError for unknown prompt override role")

    empty = tmp_path / "empty.md"
    empty.write_text("   \n")
    empty_policy = tmp_path / "empty-policy.json"
    empty_policy.write_text('{"promptOverrides": {"intents": {"review_only": "empty.md"}}}')
    try:
        Policy.from_file(empty_policy)
    except ValueError as exc:
        assert "prompt override file is empty" in str(exc)
    else:
        raise AssertionError("expected ValueError for empty prompt override")


def test_sync_after_merge_is_trusted_auto_by_default_not_auto():
    n = Notification(1, "<x@github.com>", "subj", "notifications@github.com", "", auth={"spf": True, "dkim": True, "dmarc": True})
    ctx = extract_github_context("https://github.com/gisce/erp/pull/1")

    assert Policy(trusted_orgs={"gisce"}).decision(n, ctx, "sync_after_merge") == "auto_trusted"
    assert Policy().decision(n, ctx, "sync_after_merge") == "ask"
