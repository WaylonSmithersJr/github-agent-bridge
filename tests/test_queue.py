from github_agent_bridge.models import Notification
from github_agent_bridge.policy import FeedbackLearning, Policy
from github_agent_bridge.queue import JobQueue

BODY1 = "@pilipilisbot one https://github.com/gisce/erp/pull/1#issuecomment-10"
BODY2 = "@pilipilisbot two https://github.com/gisce/erp/pull/1#issuecomment-11"
BODY_OTHER = "@pilipilisbot other https://github.com/gisce/erp/pull/2#issuecomment-12"


def notif(uid, mid, body):
    return Notification(uid=uid, message_id=mid, subject="Re: [gisce/erp] PR", from_addr="Edu <notifications@github.com>", body=body, auth={"spf": True, "dkim": True, "dmarc": True})


def policy():
    return Policy(trusted_orgs={"gisce"})


def test_enqueue_and_coalesce_same_work_key(tmp_path):
    q = JobQueue(tmp_path / "q.sqlite3")
    job1, state1 = q.enqueue(notif(1, "<1@github.com>", BODY1), policy())
    job2, state2 = q.enqueue(notif(2, "<2@github.com>", BODY2), policy())
    assert state1 == "enqueued"
    assert state2 == "coalesced"
    assert job1.id == job2.id
    assert q.stats()["pending"] == 1


def test_claim_parallel_different_work_keys_but_not_same(tmp_path):
    q = JobQueue(tmp_path / "q.sqlite3")
    q.enqueue(notif(1, "<1@github.com>", BODY1), policy())
    q.enqueue(notif(2, "<2@github.com>", BODY2), policy())
    q.enqueue(notif(3, "<3@github.com>", BODY_OTHER), policy())
    j1 = q.claim_next("w1")
    j2 = q.claim_next("w2")
    assert {j1.work_key, j2.work_key} == {"gisce/erp#1", "gisce/erp#2"}
    assert q.claim_next("w3") is None


def test_enqueue_captures_feedback_for_actionable_jobs(tmp_path, monkeypatch):
    captured = []

    def fake_capture(db_path, n, ctx, action, decision, work_intent):
        captured.append((db_path.name, n.message_id, ctx.work_key, action, decision, work_intent))
        return True

    monkeypatch.setattr("github_agent_bridge.feedback.capture_feedback", fake_capture)

    q = JobQueue(tmp_path / "q.sqlite3")
    q.enqueue(notif(1, "<1@github.com>", BODY1), policy())

    assert captured == [("q.sqlite3", "<1@github.com>", "gisce/erp#1", "reply_comment", "auto_trusted", "review_only")]


def test_duplicate_enqueue_does_not_recapture_feedback(tmp_path, monkeypatch):
    captured = []
    monkeypatch.setattr("github_agent_bridge.feedback.capture_feedback", lambda *args: captured.append(args) or True)

    q = JobQueue(tmp_path / "q.sqlite3")
    q.enqueue(notif(1, "<1@github.com>", BODY1), policy())
    q.enqueue(notif(1, "<1@github.com>", BODY1), policy())

    assert len(captured) == 1


def test_enqueue_skips_feedback_when_policy_disables_it(tmp_path, monkeypatch):
    captured = []
    monkeypatch.setattr("github_agent_bridge.feedback.capture_feedback", lambda *args: captured.append(args) or True)

    q = JobQueue(tmp_path / "q.sqlite3")
    q.enqueue(notif(1, "<1@github.com>", BODY1), Policy(trusted_orgs={"gisce"}, feedback_learning=FeedbackLearning(enabled=False)))

    assert captured == []
