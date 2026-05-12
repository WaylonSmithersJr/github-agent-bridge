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
