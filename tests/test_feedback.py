import sqlite3

import pytest

from github_agent_bridge import feedback
from github_agent_bridge.models import GitHubContext, Notification
from github_agent_bridge.queue import JobQueue


def notification(body: str | None = None):
    return Notification(
        uid=1,
        message_id="<1@github.com>",
        subject="Re: [gisce/erp] PR",
        from_addr="notifications@github.com",
        body=body or "Aquest comentari critica el comportament de l'agent. https://github.com/gisce/erp/pull/1#issuecomment-10",
    )


def context():
    return GitHubContext(["https://github.com/gisce/erp/pull/1#issuecomment-10"], "gisce/erp", 1, comment_id=10)


def test_capture_feedback_stores_candidate_event_without_synthesizing_rule(tmp_path):
    db = tmp_path / "q.sqlite3"
    JobQueue(db)

    assert feedback.capture_feedback(db, notification(), context(), "reply_comment", "auto_trusted", "review_only")

    with sqlite3.connect(db) as con:
        event = con.execute("SELECT scope, classification, confidence, memorable FROM feedback_events").fetchone()
        rule_count = con.execute("SELECT count(*) FROM feedback_rules").fetchone()[0]

    assert event == ("repo:gisce/erp", "unreviewed", 0.0, 0)
    assert rule_count == 0


def test_capture_feedback_deduplicates_events(tmp_path):
    db = tmp_path / "q.sqlite3"
    JobQueue(db)
    n = notification()

    feedback.capture_feedback(db, n, context(), "reply_comment", "auto_trusted", "review_only")
    feedback.capture_feedback(db, n, context(), "reply_comment", "auto_trusted", "review_only")

    assert len(feedback.list_events(db, "repo:gisce/erp")) == 1
    assert feedback.list_rules(db, "repo:gisce/erp") == []


def test_capture_feedback_ignores_non_actionable_decisions(tmp_path):
    db = tmp_path / "q.sqlite3"
    JobQueue(db)

    assert feedback.capture_feedback(db, notification(), context(), "archive_notification", "auto", "work_allowed") is False
    assert feedback.list_events(db) == []


def test_add_rule_creates_curated_agent_rule(tmp_path):
    db = tmp_path / "q.sqlite3"
    JobQueue(db)
    feedback.capture_feedback(db, notification(), context(), "reply_comment", "auto_trusted", "review_only")
    event_id = feedback.list_events(db, "repo:gisce/erp")[0]["id"]

    rule = feedback.add_rule(
        db,
        scope="repo:gisce/erp",
        rule_type="style_preference",
        rule="Avoid generic acknowledgements; answer with concrete repo-specific evidence.",
        confidence=0.8,
        source_events=[event_id],
    )

    assert rule["scope"] == "repo:gisce/erp"
    assert rule["type"] == "style_preference"
    assert rule["confidence"] == 0.8
    assert rule["source_events"] == [event_id]
    assert feedback.list_rules(db, "repo:gisce/erp", min_confidence=0.75) == [rule]
    assert feedback.list_rules(db, "repo:gisce/erp", min_confidence=0.95) == []


def test_add_rule_rejects_invalid_confidence(tmp_path):
    db = tmp_path / "q.sqlite3"
    JobQueue(db)

    with pytest.raises(ValueError, match="confidence"):
        feedback.add_rule(db, "repo:gisce/erp", "style_preference", "Rule", 1.7)
