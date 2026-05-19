from github_agent_bridge.dispatch import DispatchResult
from github_agent_bridge.executor import ExecutorConfig, ExecutorPool
from github_agent_bridge.models import Notification
from github_agent_bridge.policy import Policy
from github_agent_bridge.queue import JobQueue


class FakeGitHub:
    def __init__(self, assigned: bool, mentioned: bool = True, non_actionable_review: bool = False, authored: bool = False, answered_url: str | None = None):
        self.assigned = assigned
        self.mentioned = mentioned
        self.non_actionable_review = non_actionable_review
        self.authored = authored
        self.answered_url = answered_url
        self.followup_url = answered_url or "https://github.com/gisce/erp/issues/27315#issuecomment-2"
        self.eyes = 0
        self.acks = 0
        self.eye_comment_ids = []

    def is_assigned_to_current_user(self, ctx):
        return self.assigned

    def is_pull_request_authored_by_current_user(self, ctx):
        return self.authored

    def issue_comment_addresses_current_user(self, ctx):
        return self.mentioned

    def is_non_actionable_review(self, ctx):
        return self.non_actionable_review

    def current_user_commented_after(self, ctx):
        return self.answered_url

    def visible_followup_after_trigger(self, ctx):
        return self.followup_url

    def react_eyes(self, ctx):
        self.eyes += 1
        self.eye_comment_ids.append(ctx.comment_id)
        return True

    def react_ack_no_comment(self, ctx):
        self.acks += 1
        return True


class RecordingDispatcher:
    def __init__(self):
        self.jobs = []

    def dispatch(self, job, policy, reaction_ok=None):
        self.jobs.append(job)
        return DispatchResult(True, 0, "ok", "", False, reaction_ok, ["openclaw"])


def enqueue_pr_review(queue: JobQueue):
    notification = Notification(
        uid=2,
        message_id="<gisce/erp/pull/27737/review/4282224025@github.com>",
        subject="Re: [gisce/erp] Endurecer ir.values sin nuevos pickles (PR #27737)",
        from_addr="notifications@github.com",
        body="Copilot wasn't able to review any files in this pull request. https://github.com/gisce/erp/pull/27737#pullrequestreview-4282224025",
    )
    job, state = queue.enqueue(notification, Policy(trusted_orgs={"gisce"}))
    assert state == "enqueued"
    assert job is not None
    assert job.action == "reply_comment"
    assert job.context.review_id == 4282224025
    return job


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


def test_unassigned_mentioned_pr_comment_stays_review_only(tmp_path):
    queue = JobQueue(tmp_path / "bridge.sqlite3")
    enqueue_pr_comment(queue)
    dispatcher = RecordingDispatcher()

    pool = ExecutorPool(queue, Policy(trusted_orgs={"gisce"}), dispatcher, github=FakeGitHub(assigned=False, mentioned=True), config=ExecutorConfig(run_once=True))
    assert pool.work_one("worker-test") is True

    assert dispatcher.jobs[0].work_intent == "review_only"
    stored = queue.get(dispatcher.jobs[0].id)
    assert stored is not None
    assert stored.work_intent == "review_only"


def test_coalesced_notifications_are_reacted_to_before_dispatch(tmp_path):
    queue = JobQueue(tmp_path / "bridge.sqlite3")
    enqueue_pr_comment(queue)
    notification = Notification(
        uid=2,
        message_id="<gisce/erp/pull/27315/c2@github.com>",
        subject="Re: [gisce/erp] Permitir caller en los dominios (PR #27315)",
        from_addr="notifications@github.com",
        body="@pilipilisbot segon comentari https://github.com/gisce/erp/pull/27315#issuecomment-2",
    )
    job, state = queue.enqueue(notification, Policy(trusted_orgs={"gisce"}))
    assert state == "coalesced"
    dispatcher = RecordingDispatcher()
    github = FakeGitHub(assigned=False, mentioned=True)

    pool = ExecutorPool(queue, Policy(trusted_orgs={"gisce"}), dispatcher, github=github, config=ExecutorConfig(run_once=True))
    assert pool.work_one("worker-test") is True

    assert len(dispatcher.jobs) == 1
    assert dispatcher.jobs[0].id == job.id
    assert 2 in github.eye_comment_ids


def test_bot_authored_pr_review_comment_upgrades_to_work_allowed(tmp_path):
    queue = JobQueue(tmp_path / "bridge.sqlite3")
    enqueue_pr_comment(queue)
    dispatcher = RecordingDispatcher()

    pool = ExecutorPool(queue, Policy(trusted_orgs={"gisce"}), dispatcher, github=FakeGitHub(assigned=False, mentioned=True, authored=True), config=ExecutorConfig(run_once=True))
    assert pool.work_one("worker-test") is True

    assert dispatcher.jobs[0].work_intent == "work_allowed"
    stored = queue.get(dispatcher.jobs[0].id)
    assert stored is not None
    assert stored.work_intent == "work_allowed"


def test_unassigned_unmentioned_pr_comment_reacts_without_dispatch(tmp_path):
    queue = JobQueue(tmp_path / "bridge.sqlite3")
    job = enqueue_pr_comment(queue)
    dispatcher = RecordingDispatcher()
    github = FakeGitHub(assigned=False, mentioned=False)

    pool = ExecutorPool(queue, Policy(trusted_orgs={"gisce"}), dispatcher, github=github, config=ExecutorConfig(run_once=True))
    assert pool.work_one("worker-test") is True

    assert dispatcher.jobs == []
    assert github.eyes == 1
    assert github.acks == 1
    stored = queue.get(job.id)
    assert stored is not None
    assert stored.status == "done"


def test_retry_skips_dispatch_when_bot_already_answered(tmp_path):
    queue = JobQueue(tmp_path / "bridge.sqlite3")
    job = enqueue_pr_comment(queue)
    dispatcher = RecordingDispatcher()
    github = FakeGitHub(assigned=True, answered_url="https://github.com/gisce/erp/pull/27315#issuecomment-2")

    pool = ExecutorPool(queue, Policy(trusted_orgs={"gisce"}), dispatcher, github=github, config=ExecutorConfig(run_once=True))
    assert pool.work_one("worker-test") is True

    assert dispatcher.jobs == []
    assert github.eyes == 0
    stored = queue.get(job.id)
    assert stored is not None
    assert stored.status == "done"


def test_work_allowed_dispatch_blocks_without_visible_github_followup(tmp_path):
    queue = JobQueue(tmp_path / "bridge.sqlite3")
    job = enqueue_pr_comment(queue)
    dispatcher = RecordingDispatcher()
    github = FakeGitHub(assigned=True)
    github.followup_url = None

    pool = ExecutorPool(queue, Policy(trusted_orgs={"gisce"}), dispatcher, github=github, config=ExecutorConfig(run_once=True))
    assert pool.work_one("worker-test") is True

    assert dispatcher.jobs
    stored = queue.get(job.id)
    assert stored is not None
    assert stored.status == "blocked"
    assert stored.last_error == "ok"


def test_non_actionable_review_reacts_without_dispatch_even_when_assigned(tmp_path):
    queue = JobQueue(tmp_path / "bridge.sqlite3")
    job = enqueue_pr_review(queue)
    dispatcher = RecordingDispatcher()
    github = FakeGitHub(assigned=True, non_actionable_review=True)

    pool = ExecutorPool(queue, Policy(trusted_orgs={"gisce"}), dispatcher, github=github, config=ExecutorConfig(run_once=True))
    assert pool.work_one("worker-test") is True

    assert dispatcher.jobs == []
    assert github.eyes == 1
    assert github.acks == 1
    stored = queue.get(job.id)
    assert stored is not None
    assert stored.status == "done"
