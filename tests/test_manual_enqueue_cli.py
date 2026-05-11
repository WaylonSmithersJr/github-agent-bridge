import json

from github_agent_bridge.cli import _parse_github_comment_url, notification_from_comment_url
from github_agent_bridge.parser import extract_github_context


def test_parse_github_comment_url():
    assert _parse_github_comment_url("https://github.com/gisce/erp/pull/27675#issuecomment-4419572864") == ("gisce/erp", 27675, 4419572864)


def test_notification_from_comment_url_builds_bridge_notification(monkeypatch):
    def fake_gh(args, gh_bin="gh"):
        if args == ["api", "repos/gisce/erp/issues/comments/4419572864"]:
            return {
                "html_url": "https://github.com/gisce/erp/pull/27675#issuecomment-4419572864",
                "body": "@pilipilisbot pots mirar això?",
            }
        if args == ["api", "repos/gisce/erp/issues/27675"]:
            return {"title": "Eliminar descarga de módulos remotos", "pull_request": {}}
        raise AssertionError(args)

    monkeypatch.setattr("github_agent_bridge.cli._run_gh_json", fake_gh)

    n = notification_from_comment_url("https://github.com/gisce/erp/pull/27675#issuecomment-4419572864")
    ctx = extract_github_context(n.body)

    assert n.message_id == "<manual/gisce/erp/issues/27675/c4419572864@github.com>"
    assert n.subject == "Re: [gisce/erp] Eliminar descarga de módulos remotos (PR #27675)"
    assert n.from_addr == "GitHub <notifications@github.com>"
    assert n.auth == {"spf": True, "dkim": True, "dmarc": True}
    assert ctx.repo == "gisce/erp"
    assert ctx.issue_number == 27675
    assert ctx.comment_id == 4419572864
