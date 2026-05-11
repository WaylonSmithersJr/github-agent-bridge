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
