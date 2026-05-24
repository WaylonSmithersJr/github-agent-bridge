from __future__ import annotations

import argparse
import email
import json
import mailbox
import os
import re
import subprocess
import sys
from pathlib import Path

from . import feedback
from .actors import backfill_trigger_actors
from .dashboard_data import inspect_db_read_only, list_jobs
from .dispatch import GitHubClient, OpenClawDispatcher, RunMode
from .executor import ExecutorConfig, ExecutorPool
from .models import Notification, utc_now
from .monitor import MonitorThresholds, monitor, report_json
from .observability import DEFAULT_PROCESS_SAMPLE_RETENTION_SECONDS
from .parser import decode_header_value, extract_body_text, parse_auth_results
from .policy import Policy
from .queue import JobQueue
from .reader import ImapConfig, ImapReader

DEFAULT_DB = os.path.expanduser("~/.local/state/github-agent-bridge/bridge.sqlite3")
DEFAULT_POLICY = os.path.expanduser("~/.config/github-agent-bridge/policy.json")


def load_policy(path: str | None) -> Policy:
    p = path or DEFAULT_POLICY
    return Policy.from_file(p) if Path(p).exists() else Policy()


def msg_to_notification(msg, uid: int | None = None) -> Notification | None:
    from_addr = decode_header_value(msg.get("From", ""))
    if "notifications@github.com" not in from_addr.lower():
        return None
    return Notification(
        uid=uid,
        message_id=decode_header_value(msg.get("Message-ID", "")),
        subject=decode_header_value(msg.get("Subject", "")),
        from_addr=from_addr,
        body=extract_body_text(msg),
        auth=parse_auth_results(msg),
    )


def _run_gh_json(args: list[str], gh_bin: str = "gh") -> dict:
    proc = subprocess.run([gh_bin, *args], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"gh failed ({proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}")
    return json.loads(proc.stdout)


def _parse_github_comment_url(url: str) -> tuple[str, int, int]:
    match = re.search(r"github\.com/([^/]+/[^/]+)/(?:issues|pull)/(\d+)#issuecomment-(\d+)", url)
    if not match:
        raise SystemExit("expected a GitHub issue/PR issue-comment URL like https://github.com/owner/repo/pull/123#issuecomment-456")
    return match.group(1).lower(), int(match.group(2)), int(match.group(3))


def notification_from_comment_url(url: str, gh_bin: str = "gh", message_id_prefix: str = "manual") -> Notification:
    repo, issue_number, comment_id = _parse_github_comment_url(url)
    comment = _run_gh_json(["api", f"repos/{repo}/issues/comments/{comment_id}"], gh_bin)
    issue = _run_gh_json(["api", f"repos/{repo}/issues/{issue_number}"], gh_bin)
    html_url = comment.get("html_url") or url
    body = f"{comment.get('body') or ''}\n\n{html_url}\n"
    subject_kind = "PR" if "pull_request" in issue else "Issue"
    subject = f"Re: [{repo}] {issue.get('title') or subject_kind} ({subject_kind} #{issue_number})"
    user = comment.get("user") if isinstance(comment.get("user"), dict) else {}
    return Notification(
        uid=None,
        message_id=f"<{message_id_prefix}/{repo}/issues/{issue_number}/c{comment_id}@github.com>",
        subject=subject,
        from_addr=f"{user.get('login') or 'GitHub'} <notifications@github.com>",
        body=body,
        received_at=utc_now(),
        auth={"spf": True, "dkim": True, "dmarc": True},
    )


def cmd_init_db(args: argparse.Namespace) -> int:
    JobQueue(args.db)
    print(f"initialized {args.db}")
    return 0


def cmd_enqueue_json(args: argparse.Namespace) -> int:
    q = JobQueue(args.db); policy = load_policy(args.policy)
    data = json.loads(Path(args.file).read_text(encoding="utf-8")) if args.file != "-" else json.load(__import__("sys").stdin)
    n = Notification(**data)
    job, state = q.enqueue(n, policy)
    print(json.dumps({"state": state, "job_id": job.id if job else None, "work_key": job.work_key if job else None, "trigger_actor": job.trigger_actor if job else None, "trigger_actor_avatar_url": job.trigger_actor_avatar_url if job else None}, ensure_ascii=False))
    return 0


def cmd_enqueue_comment_url(args: argparse.Namespace) -> int:
    q = JobQueue(args.db); policy = load_policy(args.policy)
    n = notification_from_comment_url(args.url, args.gh_bin, args.message_id_prefix)
    job, state = q.enqueue(n, policy)
    print(json.dumps({
        "state": state,
        "job_id": job.id if job else None,
        "work_key": job.work_key if job else None,
        "trigger_actor": job.trigger_actor if job else None,
        "trigger_actor_avatar_url": job.trigger_actor_avatar_url if job else None,
        "message_id": n.message_id,
        "subject": n.subject,
    }, ensure_ascii=False))
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    q = JobQueue(args.db); policy = load_policy(args.policy)
    path = Path(args.path)
    count = 0; skipped = 0
    messages = []
    if path.is_dir():
        messages = [email.message_from_bytes(p.read_bytes()) for p in sorted(path.iterdir()) if p.is_file()]
    elif args.format == "mbox":
        messages = list(mailbox.mbox(path))
    else:
        messages = [email.message_from_bytes(path.read_bytes())]
    for idx, msg in enumerate(messages, 1):
        n = msg_to_notification(msg, uid=args.uid_base + idx if args.uid_base is not None else None)
        if not n:
            skipped += 1; continue
        job, state = q.enqueue(n, policy)
        count += 1
        if args.verbose:
            print(json.dumps({"state": state, "job_id": job.id if job else None, "work_key": job.work_key if job else None, "trigger_actor": job.trigger_actor if job else None, "trigger_actor_avatar_url": job.trigger_actor_avatar_url if job else None, "subject": n.subject}, ensure_ascii=False))
    print(json.dumps({"github_messages": count, "skipped": skipped, "mode": "replay-no-side-effects"}, ensure_ascii=False))
    return 0


def cmd_read_imap_once(args: argparse.Namespace) -> int:
    q = JobQueue(args.db); policy = load_policy(args.policy)
    cfg = ImapConfig(args.imap_host, args.imap_port, args.email, args.password, args.mailbox)
    count = ImapReader(cfg, q, policy, mark_seen=args.mark_seen).fetch_once()
    print(json.dumps({"enqueued_or_seen": count, "mark_seen": args.mark_seen}, ensure_ascii=False))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    q = JobQueue(args.db); policy = load_policy(args.policy)
    mode = RunMode(args.mode)
    dispatcher = OpenClawDispatcher(
        args.openclaw_bin,
        args.node_bin,
        args.channel,
        args.to,
        args.timeout,
        mode=mode,
        review_timeout_seconds=args.review_timeout,
        work_timeout_seconds=args.work_timeout,
        cli_grace_seconds=args.cli_grace,
        feedback_db_path=args.db,
    )
    pool = ExecutorPool(q, policy, dispatcher, GitHubClient(args.gh_bin, mode=mode), ExecutorConfig(args.workers, args.idle_sleep, args.once))
    pool.run()
    return 0


def job_dict(job):
    if isinstance(job, dict):
        return {
            "id": job["id"],
            "work_key": job["work_key"],
            "status": job["status"],
            "action": job["action"],
            "intent": job["intent"],
            "attempts": job["attempts"],
            "coalesced": job["coalesced_count"],
            "trigger_actor": job.get("trigger_actor"),
            "trigger_actor_avatar_url": job.get("trigger_actor_avatar_url"),
            "updated_at": job["updated_at"],
            "error": job["last_error"],
        }
    return {"id": job.id, "work_key": job.work_key, "status": job.status, "action": job.action, "intent": job.work_intent, "attempts": job.attempts, "coalesced": job.coalesced_count, "trigger_actor": job.trigger_actor, "trigger_actor_avatar_url": job.trigger_actor_avatar_url, "updated_at": job.updated_at, "error": job.last_error}


def cmd_status(args: argparse.Namespace) -> int:
    metrics = inspect_db_read_only(args.db)
    print(json.dumps({"stats": metrics.get("counts", {}), "oldest_pending_age_seconds": metrics.get("oldest_pending_age_seconds")}, ensure_ascii=False, indent=2))
    return 0


def cmd_jobs(args: argparse.Namespace) -> int:
    rows = list_jobs(args.db, status_filter=args.status, limit=args.limit)
    print(json.dumps([job_dict(j) for j in rows], ensure_ascii=False, indent=2))
    return 0


def cmd_retry(args: argparse.Namespace) -> int:
    ok = JobQueue(args.db).retry(args.job_id)
    print(json.dumps({"job_id": args.job_id, "requeued": ok}, ensure_ascii=False))
    return 0 if ok else 1


def cmd_dismiss(args: argparse.Namespace) -> int:
    ok = JobQueue(args.db).dismiss(args.job_id, args.reason)
    print(json.dumps({"job_id": args.job_id, "dismissed": ok}, ensure_ascii=False))
    return 0 if ok else 1


def cmd_unlock_stale(args: argparse.Namespace) -> int:
    n = JobQueue(args.db).unlock_stale(args.older_than)
    print(json.dumps({"unlocked": n}, ensure_ascii=False))
    return 0


def cmd_backfill_trigger_actors(args: argparse.Namespace) -> int:
    result = backfill_trigger_actors(args.db, gh_bin=args.gh_bin, limit=args.limit, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_monitor(args: argparse.Namespace) -> int:
    thresholds = MonitorThresholds(
        pending_warn_seconds=args.pending_warn_seconds,
        review_running_warn_seconds=args.review_running_warn_seconds,
        work_running_warn_seconds=args.work_running_warn_seconds,
    )
    report = monitor(
        args.db,
        executor_unit=args.executor_unit,
        reader_timer_unit=args.reader_timer_unit,
        reader_service_unit=args.reader_service_unit,
        thresholds=thresholds,
        check_systemd=not args.no_systemd,
        persist_observability=not args.no_persist_observability,
        process_sample_retention_seconds=args.process_sample_retention_seconds,
    )
    print(report_json(report) if args.json else report.text())
    return 0 if report.ok else 2


def cmd_feedback_rules(args: argparse.Namespace) -> int:
    print(json.dumps({"rules": feedback.list_rules(args.db, args.scope, args.min_confidence)}, ensure_ascii=False, indent=2))
    return 0


def cmd_feedback_events(args: argparse.Namespace) -> int:
    print(json.dumps({"events": feedback.list_events(args.db, args.scope, args.limit)}, ensure_ascii=False, indent=2))
    return 0


def cmd_feedback_rule_add(args: argparse.Namespace) -> int:
    rule = feedback.add_rule(args.db, args.scope, args.type, args.rule, args.confidence, args.source_event)
    print(json.dumps({"rule": rule}, ensure_ascii=False, indent=2))
    return 0


def cmd_feedback_learn(args: argparse.Namespace) -> int:
    policy = load_policy(args.policy)
    if not policy.feedback_learning.enabled:
        print(json.dumps({"processed": 0, "disabled": True}, ensure_ascii=False, indent=2))
        return 0
    classifier_override = policy.prompt_overrides.rule_path("feedback_classifier")
    result = feedback.learn_from_events(
        args.db,
        openclaw_bin=args.openclaw_bin,
        model=args.model or policy.feedback_learning.model,
        thinking=args.thinking or policy.feedback_learning.thinking,
        session_id=args.session_id or policy.feedback_learning.session_id,
        limit=args.limit or policy.feedback_learning.max_events_per_run,
        auto_approve_confidence=args.auto_approve_confidence if args.auto_approve_confidence is not None else policy.feedback_learning.auto_approve_confidence,
        timeout=args.timeout,
        prompt_template=feedback.load_prompt_override(classifier_override) if classifier_override else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_feedback_proposals(args: argparse.Namespace) -> int:
    print(json.dumps({"proposals": feedback.list_proposals(args.db, args.status, args.limit)}, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=Path(sys.argv[0]).name)
    p.add_argument("--db", default=DEFAULT_DB)
    p.add_argument("--policy", default=None)
    sub = p.add_subparsers(required=True)
    s = sub.add_parser("init-db"); s.set_defaults(func=cmd_init_db)
    s = sub.add_parser("enqueue-json"); s.add_argument("file"); s.set_defaults(func=cmd_enqueue_json)
    s = sub.add_parser("enqueue-comment-url", help="fetch a GitHub issue/PR comment URL and enqueue it as a trusted notification")
    s.add_argument("url")
    s.add_argument("--gh-bin", default="gh")
    s.add_argument("--message-id-prefix", default="manual")
    s.set_defaults(func=cmd_enqueue_comment_url)
    s = sub.add_parser("replay"); s.add_argument("path"); s.add_argument("--format", choices=["eml", "mbox"], default="eml"); s.add_argument("--uid-base", type=int); s.add_argument("--verbose", action="store_true"); s.set_defaults(func=cmd_replay)
    s = sub.add_parser("read-imap-once")
    s.add_argument("--imap-host", default=os.getenv("GITHUB_AGENT_BRIDGE_IMAP_HOST", "imap.gmail.com"))
    s.add_argument("--imap-port", type=int, default=int(os.getenv("GITHUB_AGENT_BRIDGE_IMAP_PORT", "993")))
    s.add_argument("--email", default=os.getenv("GITHUB_AGENT_BRIDGE_EMAIL", ""))
    s.add_argument("--password", default=os.getenv("GITHUB_AGENT_BRIDGE_PASSWORD", ""))
    s.add_argument("--mailbox", default="INBOX"); s.add_argument("--mark-seen", action="store_true", help="mark GitHub notifications as seen; leave off for shadow mode")
    s.set_defaults(func=cmd_read_imap_once)
    s = sub.add_parser("run")
    s.add_argument("--mode", choices=[m.value for m in RunMode], default=RunMode.SHADOW.value)
    s.add_argument("--workers", type=int, default=4); s.add_argument("--once", action="store_true")
    s.add_argument("--idle-sleep", type=float, default=1.0)
    s.add_argument("--timeout", type=int, default=3600, help="fallback OpenClaw agent timeout in seconds")
    s.add_argument("--review-timeout", type=int, default=900, help="OpenClaw agent timeout for review_only jobs")
    s.add_argument("--work-timeout", type=int, default=3600, help="OpenClaw agent timeout for work_allowed jobs")
    s.add_argument("--cli-grace", type=int, default=60, help="extra seconds the bridge waits for openclaw CLI cleanup after agent timeout")
    s.add_argument("--openclaw-bin", default=os.getenv("OPENCLAW_BIN", "openclaw")); s.add_argument("--node-bin", default=os.getenv("NODE_BIN"))
    s.add_argument("--gh-bin", default="gh"); s.add_argument("--channel", default=os.getenv("GITHUB_AGENT_BRIDGE_DEFAULT_CHANNEL", "telegram")); s.add_argument("--to", default=os.getenv("GITHUB_AGENT_BRIDGE_DEFAULT_TO", ""))
    s.set_defaults(func=cmd_run)
    s = sub.add_parser("status"); s.set_defaults(func=cmd_status)
    s = sub.add_parser("jobs"); s.add_argument("--status"); s.add_argument("--limit", type=int, default=20); s.set_defaults(func=cmd_jobs)
    s = sub.add_parser("retry"); s.add_argument("job_id", type=int); s.set_defaults(func=cmd_retry)
    s = sub.add_parser("dismiss"); s.add_argument("job_id", type=int); s.add_argument("--reason", required=True); s.set_defaults(func=cmd_dismiss)
    s = sub.add_parser("unlock-stale"); s.add_argument("--older-than", type=int, default=1800); s.set_defaults(func=cmd_unlock_stale)
    s = sub.add_parser("backfill-trigger-actors", help="fill missing job trigger_actor values from stored GitHub context")
    s.add_argument("--gh-bin", default="gh")
    s.add_argument("--limit", type=int, default=None)
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(func=cmd_backfill_trigger_actors)
    s = sub.add_parser("monitor")
    s.add_argument("--json", action="store_true", help="emit structured JSON")
    s.add_argument("--no-systemd", action="store_true", help="skip systemd unit checks")
    s.add_argument("--executor-unit", default="github-agent-bridge.service")
    s.add_argument("--reader-timer-unit", default="github-agent-bridge-reader.timer")
    s.add_argument("--reader-service-unit", default="github-agent-bridge-reader.service")
    s.add_argument("--pending-warn-seconds", type=int, default=300)
    s.add_argument("--review-running-warn-seconds", type=int, default=1200)
    s.add_argument("--work-running-warn-seconds", type=int, default=4200)
    s.add_argument(
        "--process-sample-retention-seconds",
        type=int,
        default=int(os.getenv("GITHUB_AGENT_BRIDGE_PROCESS_SAMPLE_RETENTION_SECONDS", str(DEFAULT_PROCESS_SAMPLE_RETENTION_SECONDS))),
    )
    s.add_argument("--no-persist-observability", action="store_true", help="skip writing process samples and alert observations")
    s.set_defaults(func=cmd_monitor)
    s = sub.add_parser("feedback-rules", help="list curated feedback rules")
    s.add_argument("--scope", default="", help="filter by exact scope or scope prefix, e.g. repo:owner/name")
    s.add_argument("--min-confidence", type=float, default=None)
    s.set_defaults(func=cmd_feedback_rules)
    s = sub.add_parser("feedback-events", help="list captured feedback candidates")
    s.add_argument("--scope", default="", help="filter by exact scope or scope prefix, e.g. repo:owner/name")
    s.add_argument("--limit", type=int, default=20)
    s.set_defaults(func=cmd_feedback_events)
    s = sub.add_parser("feedback-rule-add", help="add or reinforce a curated feedback rule")
    s.add_argument("--scope", required=True, help="rule scope, e.g. repo:owner/name")
    s.add_argument("--type", required=True, help="rule category, e.g. style_preference or operating_rule")
    s.add_argument("--rule", required=True, help="curated rule text")
    s.add_argument("--confidence", type=float, default=0.8)
    s.add_argument("--source-event", action="append", default=[], help="feedback event id that supports this rule")
    s.set_defaults(func=cmd_feedback_rule_add)
    s = sub.add_parser("feedback-learn", help="autonomously classify feedback candidates and promote high-confidence rules")
    s.add_argument("--limit", type=int, default=None)
    s.add_argument("--openclaw-bin", default=os.getenv("GITHUB_AGENT_BRIDGE_OPENCLAW_BIN", os.getenv("OPENCLAW_BIN", "openclaw")))
    s.add_argument("--model", default=None)
    s.add_argument("--thinking", default=None)
    s.add_argument("--session-id", default=None)
    s.add_argument("--timeout", type=int, default=180)
    s.add_argument("--auto-approve-confidence", type=float, default=None)
    s.set_defaults(func=cmd_feedback_learn)
    s = sub.add_parser("feedback-proposals", help="list autonomous feedback learning proposals")
    s.add_argument("--status", choices=["", "approved", "rejected", "proposed", "error"], default="")
    s.add_argument("--limit", type=int, default=20)
    s.set_defaults(func=cmd_feedback_proposals)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
