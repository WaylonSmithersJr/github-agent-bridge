from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .dispatch import GitHubClient, OpenClawDispatcher
from .executor import ExecutorConfig, ExecutorPool
from .models import Notification
from .policy import Policy
from .queue import JobQueue
from .reader import ImapConfig, ImapReader

DEFAULT_DB = os.path.expanduser("~/.local/state/github-agent-bridge/bridge.sqlite3")
DEFAULT_POLICY = os.path.expanduser("~/.config/github-agent-bridge/policy.json")


def load_policy(path: str | None) -> Policy:
    p = path or DEFAULT_POLICY
    return Policy.from_file(p) if Path(p).exists() else Policy()


def cmd_init_db(args: argparse.Namespace) -> int:
    JobQueue(args.db)
    print(f"initialized {args.db}")
    return 0


def cmd_enqueue_json(args: argparse.Namespace) -> int:
    q = JobQueue(args.db); policy = load_policy(args.policy)
    data = json.loads(Path(args.file).read_text(encoding="utf-8")) if args.file != "-" else json.load(__import__('sys').stdin)
    n = Notification(**data)
    job, state = q.enqueue(n, policy)
    print(json.dumps({"state": state, "job_id": job.id if job else None, "work_key": job.work_key if job else None}, ensure_ascii=False))
    return 0


def cmd_read_imap_once(args: argparse.Namespace) -> int:
    q = JobQueue(args.db); policy = load_policy(args.policy)
    cfg = ImapConfig(args.imap_host, args.imap_port, args.email, args.password, args.mailbox)
    count = ImapReader(cfg, q, policy).fetch_once()
    print(json.dumps({"enqueued_or_seen": count}, ensure_ascii=False))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    q = JobQueue(args.db); policy = load_policy(args.policy)
    dispatcher = OpenClawDispatcher(args.openclaw_bin, args.node_bin, args.channel, args.to, args.timeout)
    pool = ExecutorPool(q, policy, dispatcher, GitHubClient(args.gh_bin), ExecutorConfig(args.workers, args.idle_sleep, args.once))
    pool.run()
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    q = JobQueue(args.db)
    print(json.dumps({"stats": q.stats(), "oldest_pending_age_seconds": q.pending_age_seconds()}, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="github-agent-bridge")
    p.add_argument("--db", default=DEFAULT_DB)
    p.add_argument("--policy", default=None)
    sub = p.add_subparsers(required=True)
    s = sub.add_parser("init-db"); s.set_defaults(func=cmd_init_db)
    s = sub.add_parser("enqueue-json"); s.add_argument("file"); s.set_defaults(func=cmd_enqueue_json)
    s = sub.add_parser("read-imap-once")
    s.add_argument("--imap-host", default=os.getenv("GITHUB_AGENT_BRIDGE_IMAP_HOST", "imap.gmail.com"))
    s.add_argument("--imap-port", type=int, default=int(os.getenv("GITHUB_AGENT_BRIDGE_IMAP_PORT", "993")))
    s.add_argument("--email", default=os.getenv("GITHUB_AGENT_BRIDGE_EMAIL", ""))
    s.add_argument("--password", default=os.getenv("GITHUB_AGENT_BRIDGE_PASSWORD", ""))
    s.add_argument("--mailbox", default="INBOX")
    s.set_defaults(func=cmd_read_imap_once)
    s = sub.add_parser("run")
    s.add_argument("--workers", type=int, default=4); s.add_argument("--once", action="store_true")
    s.add_argument("--idle-sleep", type=float, default=1.0); s.add_argument("--timeout", type=int, default=240)
    s.add_argument("--openclaw-bin", default=os.getenv("OPENCLAW_BIN", "openclaw")); s.add_argument("--node-bin", default=os.getenv("NODE_BIN"))
    s.add_argument("--gh-bin", default="gh"); s.add_argument("--channel", default="telegram"); s.add_argument("--to", default="43532269")
    s.set_defaults(func=cmd_run)
    s = sub.add_parser("status"); s.set_defaults(func=cmd_status)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
