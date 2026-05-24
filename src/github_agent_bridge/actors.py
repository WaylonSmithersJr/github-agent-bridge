from __future__ import annotations

import json
import re
import sqlite3
import subprocess
from email.utils import parseaddr
from pathlib import Path
from typing import Any

from .models import GitHubContext, Notification

LOGIN_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
RESERVED_SENDERS = {"github", "notifications"}


def normalize_github_login(value: str | None) -> str | None:
    if not value:
        return None
    login = value.strip().strip("@")
    if login.lower() in RESERVED_SENDERS:
        return None
    return login if LOGIN_RE.fullmatch(login) else None


def trigger_actor_from_notification(notification: Notification) -> str | None:
    display_name, email_addr = parseaddr(notification.from_addr)
    if "notifications@github.com" not in email_addr.lower():
        return None
    return normalize_github_login(display_name)


def actor_from_github_payload(payload: dict[str, Any]) -> str | None:
    for key in ("user", "actor", "sender"):
        value = payload.get(key)
        if isinstance(value, dict):
            login = normalize_github_login(value.get("login"))
            if login:
                return login
    return None


def actor_endpoint(ctx: GitHubContext) -> str | None:
    if not ctx.repo:
        return None
    if ctx.comment_id:
        return f"repos/{ctx.repo}/issues/comments/{ctx.comment_id}"
    if ctx.review_comment_id:
        return f"repos/{ctx.repo}/pulls/comments/{ctx.review_comment_id}"
    if ctx.review_id and ctx.issue_number:
        return f"repos/{ctx.repo}/pulls/{ctx.issue_number}/reviews/{ctx.review_id}"
    if ctx.commit_comment_id:
        return f"repos/{ctx.repo}/comments/{ctx.commit_comment_id}"
    if ctx.workflow_run_id:
        return f"repos/{ctx.repo}/actions/runs/{ctx.workflow_run_id}"
    if ctx.issue_number:
        return f"repos/{ctx.repo}/issues/{ctx.issue_number}"
    return None


def github_actor_for_context(ctx: GitHubContext, *, gh_bin: str = "gh") -> str | None:
    endpoint = actor_endpoint(ctx)
    if endpoint is None:
        return None
    proc = subprocess.run([gh_bin, "api", endpoint], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        return None
    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return None
    return actor_from_github_payload(payload if isinstance(payload, dict) else {})


def backfill_trigger_actors(db: str | Path, *, gh_bin: str = "gh", limit: int | None = None, dry_run: bool = False) -> dict[str, Any]:
    path = Path(db).expanduser()
    if not path.exists():
        return {"db_exists": False, "checked": 0, "updated": 0, "missing": 0, "dry_run": dry_run}
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    try:
        jobs_table = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='jobs'").fetchone()
        if jobs_table is None:
            return {"db_exists": True, "checked": 0, "updated": 0, "missing": 0, "dry_run": dry_run, "updates": []}
        has_actor_column = _has_column(con, "jobs", "trigger_actor")
        if not dry_run:
            _ensure_trigger_actor_column(con)
            has_actor_column = True
        where = "WHERE trigger_actor IS NULL OR trigger_actor=''" if has_actor_column else ""
        rows = con.execute(
            f"""
            SELECT id, context_json
            FROM jobs
            {where}
            ORDER BY id
            LIMIT ?
            """,
            (max(1, limit or 1000000),),
        ).fetchall()
        checked = updated = missing = 0
        updates: list[dict[str, Any]] = []
        for row in rows:
            checked += 1
            try:
                ctx = GitHubContext.from_json(row["context_json"])
            except (TypeError, json.JSONDecodeError):
                missing += 1
                continue
            actor = github_actor_for_context(ctx, gh_bin=gh_bin)
            if not actor:
                missing += 1
                continue
            updates.append({"job_id": int(row["id"]), "trigger_actor": actor})
            updated += 1
            if not dry_run:
                con.execute("UPDATE jobs SET trigger_actor=? WHERE id=?", (actor, row["id"]))
        if not dry_run:
            con.commit()
        return {"db_exists": True, "checked": checked, "updated": updated, "missing": missing, "dry_run": dry_run, "updates": updates}
    finally:
        con.close()


def _has_column(con: sqlite3.Connection, table: str, column: str) -> bool:
    exists = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    if exists is None:
        return False
    return column in {row["name"] for row in con.execute(f"PRAGMA table_info({table})")}


def _ensure_trigger_actor_column(con: sqlite3.Connection) -> None:
    tables = {
        "jobs": {"trigger_actor": "TEXT"},
        "coalesced_notifications": {"trigger_actor": "TEXT"},
    }
    for table, columns in tables.items():
        exists = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
        if exists is None:
            continue
        existing = {row["name"] for row in con.execute(f"PRAGMA table_info({table})")}
        for column, definition in columns.items():
            if column not in existing:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
