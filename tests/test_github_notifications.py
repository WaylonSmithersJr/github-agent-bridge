from __future__ import annotations

from github_agent_bridge.actors import trigger_actor_details_for_enqueue
from github_agent_bridge.github_notifications import list_notification_threads, notification_from_github_thread
from github_agent_bridge.models import Notification
from github_agent_bridge.parser import extract_github_context


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


def test_assignment_notification_does_not_use_issue_author_as_actor(monkeypatch):
    calls = []

    def fake_api_get(url: str, gh_bin: str):
        calls.append(url)
        if url.endswith("/issues/15"):
            return {
                "html_url": "https://github.com/owner/repo/issues/15",
                "body": "Issue body",
                "title": "Visual identity",
                "user": {"login": "WaylonSmithersJr", "avatar_url": "https://avatars.githubusercontent.com/u/1?v=4"},
            }
        raise AssertionError(f"unexpected API URL: {url}")

    monkeypatch.setattr("github_agent_bridge.github_notifications._api_get", fake_api_get)
    converted = notification_from_github_thread(
        {
            "id": "24335501208",
            "reason": "assign",
            "updated_at": "2026-06-23T09:11:23Z",
            "repository": {"full_name": "Owner/Repo"},
            "subject": {
                "title": "Visual identity",
                "type": "Issue",
                "url": "https://api.github.com/repos/owner/repo/issues/15",
                "latest_comment_url": "https://api.github.com/repos/owner/repo/issues/15",
            },
        },
        gh_bin="gh",
    )

    assert converted is not None
    assert converted.notification.from_addr == "GitHub <notifications@github.com>"
    assert "GitHub notification reason: assign" in converted.notification.body
    assert "GitHub actor:" not in converted.notification.body
    assert calls == [
        "https://api.github.com/repos/owner/repo/issues/15",
        "repos/owner/repo/issues/15",
    ]


def test_assignment_enqueue_actor_ignores_issue_author_lookup(monkeypatch):
    def fail_run(*args, **kwargs):
        raise AssertionError("issue author lookup should not run for assign notifications")

    monkeypatch.setattr("github_agent_bridge.actors.subprocess.run", fail_run)
    body = "https://github.com/owner/repo/issues/15\n\nGitHub notification reason: assign"
    notification = Notification(
        uid=1,
        message_id="<github-notification/24335501208/2026-06-23T09:11:23Z@github.com>",
        subject="Re: [owner/repo] Visual identity (Issue #15)",
        from_addr="GitHub <notifications@github.com>",
        body=body,
        received_at="2026-06-23T09:11:23Z",
        auth={"spf": True, "dkim": True, "dmarc": True},
    )

    actor = trigger_actor_details_for_enqueue(notification, extract_github_context(body), gh_bin="gh")
    assert actor is None


def test_list_notification_threads_flattens_paginated_gh_output(monkeypatch):
    calls = []

    def fake_run_gh_json(args, gh_bin):
        calls.append((args, gh_bin))
        return [[{"id": "1"}], [{"id": "2"}, None]]

    monkeypatch.setattr("github_agent_bridge.github_notifications.run_gh_json", fake_run_gh_json)

    assert list_notification_threads("custom-gh", all_threads=True) == [{"id": "1"}, {"id": "2"}]
    assert calls == [(
        ["api", "-X", "GET", "notifications", "--paginate", "--slurp", "-f", "per_page=100", "-f", "all=true"],
        "custom-gh",
    )]
