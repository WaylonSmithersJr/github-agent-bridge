from __future__ import annotations

from github_agent_bridge.github_notifications import notification_from_github_thread


def test_notification_from_github_thread_issue_comment(monkeypatch):
    calls = []

    def fake_api_get(url: str, gh_bin: str):
        calls.append(url)
        if url.endswith("/issues/comments/456"):
            return {
                "html_url": "https://github.com/owner/repo/issues/123#issuecomment-456",
                "body": "@WaylonSmithersJr pots mirar això?",
                "user": {"login": "pol", "avatar_url": "https://avatars.githubusercontent.com/u/1?v=4"},
            }
        if url.endswith("/issues/123"):
            return {"title": "Fix login", "user": {"login": "pol"}}
        raise AssertionError(f"unexpected API URL: {url}")

    monkeypatch.setattr("github_agent_bridge.github_notifications._api_get", fake_api_get)
    converted = notification_from_github_thread(
        {
            "id": "789",
            "reason": "mention",
            "updated_at": "2026-06-06T20:00:00Z",
            "repository": {"full_name": "Owner/Repo"},
            "subject": {
                "title": "Fix login",
                "type": "Issue",
                "url": "https://api.github.com/repos/owner/repo/issues/123",
                "latest_comment_url": "https://api.github.com/repos/owner/repo/issues/comments/456",
            },
        },
        gh_bin="gh",
    )

    assert converted is not None
    assert converted.thread_id == "789"
    assert converted.html_url == "https://github.com/owner/repo/issues/123#issuecomment-456"
    assert converted.notification.uid == 789
    assert converted.notification.message_id == "<github-notification/789/2026-06-06T20:00:00Z@github.com>"
    assert converted.notification.from_addr == "pol <notifications@github.com>"
    assert converted.notification.subject == "Re: [owner/repo] Fix login (Issue #123)"
    assert "https://github.com/owner/repo/issues/123#issuecomment-456" in converted.notification.body
    assert "GitHub notification reason: mention" in converted.notification.body
    assert calls == [
        "https://api.github.com/repos/owner/repo/issues/comments/456",
        "repos/owner/repo/issues/123",
    ]
