from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass

from .dispatch import GitHubClient, OpenClawDispatcher
from .policy import Policy
from .queue import JobQueue


@dataclass(frozen=True)
class ExecutorConfig:
    workers: int = 4
    idle_sleep_seconds: float = 1.0
    run_once: bool = False


class ExecutorPool:
    def __init__(self, queue: JobQueue, policy: Policy, dispatcher: OpenClawDispatcher, github: GitHubClient | None = None, config: ExecutorConfig | None = None):
        self.queue = queue
        self.policy = policy
        self.dispatcher = dispatcher
        self.github = github or GitHubClient()
        self.config = config or ExecutorConfig()
        self.stop_event = threading.Event()

    def work_one(self, worker_id: str | None = None) -> bool:
        worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        job = self.queue.claim_next(worker_id)
        if not job:
            return False
        try:
            assigned_to_bot = self.github.is_assigned_to_current_user(job.context)
            authored_by_bot = self.github.is_pull_request_authored_by_current_user(job.context)
            if job.action == "reply_comment" and job.context.comment_id:
                answered_url = self.github.current_user_commented_after(job.context)
                if answered_url:
                    summary = "bot already commented after trigger; skipped duplicate dispatch"
                    detail = f"answered_url={answered_url}"
                    self.queue.finish(job.id, "done", summary, detail)
                    return True
            if job.action == "reply_comment" and job.context.review_id and self.github.is_non_actionable_review(job.context):
                reaction_ok = self.react_eyes_for_job_contexts(job)
                ack_ok = self.github.react_ack_no_comment(job.context)
                summary = "non-actionable review; skipped dispatch"
                detail = f"eyes={reaction_ok} ack={ack_ok}"
                self.queue.finish(job.id, "done", summary, detail)
                return True
            if job.action == "reply_comment" and job.context.comment_id and not assigned_to_bot and not self.github.issue_comment_addresses_current_user(job.context):
                reaction_ok = self.react_eyes_for_job_contexts(job)
                ack_ok = self.github.react_ack_no_comment(job.context)
                summary = "comment not addressed to bot and bot not assigned; skipped dispatch"
                detail = f"eyes={reaction_ok} ack={ack_ok}"
                self.queue.finish(job.id, "done", summary, detail)
                return True
            if job.action == "reply_comment" and job.work_intent == "review_only" and (assigned_to_bot or authored_by_bot):
                reason = "PR/issue assigned to authenticated bot" if assigned_to_bot else "PR authored by authenticated bot"
                job = self.queue.update_work_intent(job.id, "work_allowed", f"{reason}; upgraded review-only comment to work_allowed") or job
            reaction_ok = self.react_eyes_for_job_contexts(job)
            result = self.dispatcher.dispatch(job, self.policy, reaction_ok=reaction_ok)
            if result.ok:
                summary = "👀 reaction ok + agent dispatch queued" if reaction_ok else "agent dispatch queued; reaction failed or unavailable"
                self.queue.finish(job.id, "done", summary, result.detail)
            else:
                reason = "dispatch timeout" if result.timed_out else f"dispatch failed rc={result.returncode}"
                self.queue.finish(job.id, "blocked", reason, result.detail)
        except Exception as exc:
            self.queue.finish(job.id, "blocked", f"executor exception: {type(exc).__name__}", str(exc))
        return True

    def react_eyes_for_job_contexts(self, job) -> bool:
        contexts = [job.context, *self.queue.coalesced_contexts(job.id)]
        ok = True
        seen = set()
        for ctx in contexts:
            key = (ctx.repo, ctx.issue_number, ctx.comment_id, ctx.review_comment_id, ctx.review_id)
            if key in seen:
                continue
            seen.add(key)
            ok = self.github.react_eyes(ctx) and ok
        return ok

    def _loop(self, worker_id: str) -> None:
        while not self.stop_event.is_set():
            did = self.work_one(worker_id)
            if self.config.run_once:
                return
            if not did:
                time.sleep(self.config.idle_sleep_seconds)

    def run(self) -> None:
        if self.config.run_once or self.config.workers <= 1:
            self._loop("worker-0")
            return
        threads = [threading.Thread(target=self._loop, args=(f"worker-{i}",), daemon=True) for i in range(self.config.workers)]
        for t in threads: t.start()
        try:
            while any(t.is_alive() for t in threads):
                time.sleep(0.5)
        except KeyboardInterrupt:
            self.stop_event.set()
            for t in threads: t.join(timeout=5)
