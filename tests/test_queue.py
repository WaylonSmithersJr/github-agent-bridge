from github_agent_bridge.models import Notification
from github_agent_bridge.policy import Policy
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
