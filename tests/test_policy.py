from github_agent_bridge.models import Notification
from github_agent_bridge.parser import extract_github_context
from github_agent_bridge.policy import Policy


def test_trusted_org_auto_trusted():
    body = "@pilipilisbot https://github.com/gisce/erp/issues/1#issuecomment-1"
    n = Notification(1, "<x@github.com>", "subj", "notifications@github.com", body, auth={"spf": True, "dkim": True, "dmarc": True})
    ctx = extract_github_context(body)
    assert Policy(trusted_orgs={"gisce"}).decision(n, ctx, "reply_comment") == "auto_trusted"
