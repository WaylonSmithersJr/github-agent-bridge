import sqlite3

from github_agent_bridge import feedback
from github_agent_bridge.models import GitHubContext, Notification
from github_agent_bridge.queue import JobQueue


def notification(body: str | None = None):
    return Notification(
        uid=1,
        message_id="<1@github.com>",
        subject="Re: [gisce/erp] PR",
        from_addr="notifications@github.com",
        body=body or "El primer bloc es veu clarament que ho ha escrit una IA. https://github.com/gisce/erp/pull/1#issuecomment-10",
    )


def context():
    return GitHubContext(["https://github.com/gisce/erp/pull/1#issuecomment-10"], "gisce/erp", 1, comment_id=10)


def test_capture_feedback_stores_event_and_synthesized_rule(tmp_path):
    db = tmp_path / "q.sqlite3"
    JobQueue(db)

    assert feedback.capture_feedback(db, notification(), context(), "reply_comment", "auto_trusted", "review_only")

    with sqlite3.connect(db) as con:
        event = con.execute("SELECT scope, classification, memorable FROM feedback_events").fetchone()
        rule = con.execute("SELECT scope, type, rule, observations FROM feedback_rules").fetchone()

    assert event == ("repo:gisce/erp", "style_preference", 1)
    assert rule[0:2] == ("repo:gisce/erp", "style_preference")
    assert "AI-sounding" in rule[2]
    assert rule[3] == 1


def test_capture_feedback_deduplicates_events(tmp_path):
    db = tmp_path / "q.sqlite3"
    JobQueue(db)
    n = notification()

    feedback.capture_feedback(db, n, context(), "reply_comment", "auto_trusted", "review_only")
    feedback.capture_feedback(db, n, context(), "reply_comment", "auto_trusted", "review_only")

    rules = feedback.list_rules(db, "repo:gisce/erp")
    assert len(rules) == 1
    assert rules[0]["observations"] == 1
    assert len(rules[0]["source_events"]) == 1


def test_capture_feedback_ignores_non_actionable_decisions(tmp_path):
    db = tmp_path / "q.sqlite3"
    JobQueue(db)

    assert feedback.capture_feedback(db, notification(), context(), "archive_notification", "auto", "work_allowed") is False
    assert feedback.list_rules(db) == []


def test_list_rules_filters_by_scope_and_confidence(tmp_path):
    db = tmp_path / "q.sqlite3"
    JobQueue(db)
    feedback.capture_feedback(db, notification(), context(), "reply_comment", "auto_trusted", "review_only")

    assert len(feedback.list_rules(db, "repo:gisce/erp", min_confidence=0.5)) == 1
    assert feedback.list_rules(db, "repo:other/repo", min_confidence=0.5) == []
    assert feedback.list_rules(db, "repo:gisce/erp", min_confidence=0.95) == []
