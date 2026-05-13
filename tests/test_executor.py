from github_agent_bridge.dispatch import DispatchResult
from github_agent_bridge.executor import ExecutorConfig, ExecutorPool
from github_agent_bridge.models import Notification
from github_agent_bridge.policy import Policy
from github_agent_bridge.queue import JobQueue


class FakeGitHub:
    def __init__(self, assigned: bool):
        self.assigned = assigned

    def is_assigned_to_current_user(self, ctx):
        return self.assigned

    def react_eyes(self, ctx):
        return True


class RecordingDispatcher:
    def __init__(self):
        self.jobs = []

    def dispatch(self, job, policy, reaction_ok=None):
        self.jobs.append(job)
        return DispatchResult(True, 0, "ok", "", False, reaction_ok, ["openclaw"])


def enqueue_pr_comment(queue: JobQueue):
    notification = Notification(
        uid=1,
        message_id="<gisce/erp/pull/27315/c1@github.com>",
        subject="Re: [gisce/erp] Permitir caller en los dominios (PR #27315)",
        from_addr="notifications@github.com",
        body="@pilipilisbot però la transacció en què s'executa que entra per eval_domain és readonly https://github.com/gisce/erp/pull/27315#issuecomment-1",
    )
    job, state = queue.enqueue(notification, Policy(trusted_orgs={"gisce"}))
    assert state == "enqueued"
    assert job is not None
    assert job.action == "reply_comment"
    assert job.work_intent == "review_only"
    return job


def test_assigned_pr_comment_upgrades_to_work_allowed(tmp_path):
    queue = JobQueue(tmp_path / "bridge.sqlite3")
    enqueue_pr_comment(queue)
    dispatcher = RecordingDispatcher()

    pool = ExecutorPool(queue, Policy(trusted_orgs={"gisce"}), dispatcher, github=FakeGitHub(assigned=True), config=ExecutorConfig(run_once=True))
    assert pool.work_one("worker-test") is True

    assert dispatcher.jobs[0].work_intent == "work_allowed"
    stored = queue.get(dispatcher.jobs[0].id)
    assert stored is not None
    assert stored.work_intent == "work_allowed"


def test_unassigned_pr_comment_stays_review_only(tmp_path):
    queue = JobQueue(tmp_path / "bridge.sqlite3")
    enqueue_pr_comment(queue)
    dispatcher = RecordingDispatcher()

    pool = ExecutorPool(queue, Policy(trusted_orgs={"gisce"}), dispatcher, github=FakeGitHub(assigned=False), config=ExecutorConfig(run_once=True))
    assert pool.work_one("worker-test") is True

    assert dispatcher.jobs[0].work_intent == "review_only"
    stored = queue.get(dispatcher.jobs[0].id)
    assert stored is not None
    assert stored.work_intent == "review_only"
