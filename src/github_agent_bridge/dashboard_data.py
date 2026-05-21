from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def readonly_connect(db: str | Path) -> sqlite3.Connection:
    path = Path(db).expanduser()
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def table_exists(con: sqlite3.Connection, name: str) -> bool:
    row = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
    return row is not None


def parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def duration_seconds(start: str | None, end: str | None = None) -> int | None:
    started = parse_utc(start)
    if started is None:
        return None
    finished = parse_utc(end) or datetime.now(UTC)
    return max(0, int((finished - started).total_seconds()))


def coerce_limit(value: int, maximum: int = 200) -> int:
    return max(1, min(value, maximum))


def job_summary(row: sqlite3.Row) -> dict[str, Any]:
    context = json.loads(row["context_json"] or "{}")
    return {
        "id": row["id"],
        "work_key": row["work_key"],
        "repo": row["repo"],
        "thread": row["thread"],
        "status": row["status"],
        "action": row["action"],
        "decision": row["decision"],
        "intent": row["work_intent"],
        "subject": row["subject"],
        "attempts": row["attempts"],
        "coalesced_count": row["coalesced_count"],
        "last_error": row["last_error"],
        "locked_by": row["locked_by"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "queue_wait_seconds": duration_seconds(row["created_at"], row["started_at"]) if row["started_at"] else None,
        "runtime_seconds": duration_seconds(row["started_at"], row["finished_at"]),
        "github_urls": context.get("urls", []),
    }


def where_clause(filters: dict[str, Any]) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    args: list[Any] = []
    for column, value in filters.items():
        if value is None:
            continue
        clauses.append(f"{column}=?")
        args.append(value)
    return (" WHERE " + " AND ".join(clauses), args) if clauses else ("", args)


def inspect_db_read_only(db: str | Path) -> dict[str, Any]:
    path = Path(db).expanduser()
    out: dict[str, Any] = {"db_path": str(path), "db_exists": path.exists()}
    if not path.exists():
        return out
    with readonly_connect(path) as con:
        if not table_exists(con, "jobs"):
            return out | {"schema_ok": False}
        out["schema_ok"] = True
        counts = {r["status"]: int(r["count"]) for r in con.execute("SELECT status, count(*) count FROM jobs GROUP BY status")}
        out["counts"] = counts
        out.update(counts)
        pending_age = con.execute("SELECT CAST((julianday('now') - julianday(min(created_at))) * 86400 AS INTEGER) age FROM jobs WHERE status='pending'").fetchone()["age"]
        out["oldest_pending_age_seconds"] = None if pending_age is None else int(pending_age)
        if table_exists(con, "state"):
            state = {r["key"]: r["value"] for r in con.execute("SELECT key,value FROM state")}
            out["last_uid"] = state.get("last_uid")
        if table_exists(con, "worklog"):
            last_log = con.execute("SELECT ts, phase, summary FROM worklog ORDER BY id DESC LIMIT 1").fetchone()
            if last_log:
                out["last_worklog"] = dict(last_log)
        running_rows = con.execute(
            """
            SELECT id, work_key, work_intent, locked_by, attempts, started_at, updated_at
            FROM jobs
            WHERE status='running'
            ORDER BY id
            """
        ).fetchall()
        out["running_jobs"] = [
            {
                "id": row["id"],
                "work_key": row["work_key"],
                "intent": row["work_intent"],
                "work_intent": row["work_intent"],
                "locked_by": row["locked_by"],
                "attempts": row["attempts"],
                "age_seconds": duration_seconds(row["started_at"]),
                "idle_seconds": duration_seconds(row["updated_at"]),
                "last_worklog": _last_worklog(con, int(row["id"])),
            }
            for row in running_rows
        ]
        out["running"] = len(running_rows)
    return out


def list_jobs(
    db: str | Path,
    *,
    status_filter: str | None = None,
    repo: str | None = None,
    thread: int | None = None,
    action: str | None = None,
    intent: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    path = Path(db).expanduser()
    if not path.exists():
        return []
    filters = {"status": status_filter, "repo": repo, "thread": thread, "action": action, "work_intent": intent}
    where, args = where_clause(filters)
    if since:
        where += " AND created_at >= ?" if where else " WHERE created_at >= ?"
        args.append(since)
    if until:
        where += " AND created_at <= ?" if where else " WHERE created_at <= ?"
        args.append(until)
    args.append(coerce_limit(limit))
    with readonly_connect(path) as con:
        if not table_exists(con, "jobs"):
            return []
        rows = con.execute(f"SELECT * FROM jobs{where} ORDER BY id DESC LIMIT ?", args).fetchall()
    return [job_summary(row) for row in rows]


def get_job_detail(db: str | Path, job_id: int) -> dict[str, Any] | None:
    path = Path(db).expanduser()
    if not path.exists():
        return None
    with readonly_connect(path) as con:
        if not table_exists(con, "jobs"):
            return None
        row = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            return None
        job = job_summary(row)
        job["context"] = json.loads(row["context_json"] or "{}")
        job["metadata"] = json.loads(row["metadata_json"] or "{}")
        job["worklog"] = [
            dict(log)
            for log in con.execute(
                "SELECT id, ts, phase, summary, detail FROM worklog WHERE job_id=? ORDER BY id",
                (job_id,),
            ).fetchall()
        ] if table_exists(con, "worklog") else []
        job["coalesced_notifications"] = [
            {
                "id": row["id"],
                "uid": row["uid"],
                "message_id": row["message_id"],
                "subject": row["subject"],
                "context": json.loads(row["context_json"] or "{}"),
                "created_at": row["created_at"],
            }
            for row in con.execute(
                "SELECT * FROM coalesced_notifications WHERE job_id=? ORDER BY id",
                (job_id,),
            ).fetchall()
        ] if table_exists(con, "coalesced_notifications") else []
    return job


def job_logs(db: str | Path, job_id: int, limit: int = 100) -> list[dict[str, Any]]:
    path = Path(db).expanduser()
    if not path.exists():
        return []
    with readonly_connect(path) as con:
        if not table_exists(con, "worklog"):
            return []
        rows = con.execute(
            "SELECT id, ts, phase, summary, detail FROM worklog WHERE job_id=? ORDER BY id DESC LIMIT ?",
            (job_id, coerce_limit(limit, maximum=500)),
        ).fetchall()
    return [dict(row) for row in reversed(rows)]


def metrics_summary(db: str | Path) -> dict[str, Any]:
    path = Path(db).expanduser()
    if not path.exists():
        return {"db_exists": False, "status_counts": {}, "runtime_seconds": {}}
    with readonly_connect(path) as con:
        if not table_exists(con, "jobs"):
            return {"db_exists": True, "schema_ok": False, "status_counts": {}, "runtime_seconds": {}}
        rows = con.execute("SELECT status, repo, action, work_intent, created_at, started_at, finished_at FROM jobs").fetchall()
    status_counts = Counter(row["status"] for row in rows)
    by_repo = Counter(row["repo"] or "unknown" for row in rows)
    by_action = Counter(row["action"] for row in rows)
    by_intent = Counter(row["work_intent"] for row in rows)
    runtimes = sorted(
        seconds for seconds in (duration_seconds(row["started_at"], row["finished_at"]) for row in rows if row["finished_at"]) if seconds is not None
    )
    waits = sorted(
        seconds for seconds in (duration_seconds(row["created_at"], row["started_at"]) for row in rows if row["started_at"]) if seconds is not None
    )
    return {
        "db_exists": True,
        "schema_ok": True,
        "status_counts": dict(status_counts),
        "by_repo": dict(by_repo),
        "by_action": dict(by_action),
        "by_intent": dict(by_intent),
        "runtime_seconds": percentiles(runtimes),
        "queue_wait_seconds": percentiles(waits),
    }


def percentiles(values: list[int]) -> dict[str, int | None]:
    if not values:
        return {"median": None, "p90": None, "p99": None}
    return {
        "median": nearest_rank(values, 0.50),
        "p90": nearest_rank(values, 0.90),
        "p99": nearest_rank(values, 0.99),
    }


def nearest_rank(values: list[int], percentile: float) -> int:
    index = max(0, min(len(values) - 1, int(round(percentile * (len(values) - 1)))))
    return values[index]


def _last_worklog(con: sqlite3.Connection, job_id: int) -> dict[str, Any] | None:
    if not table_exists(con, "worklog"):
        return None
    row = con.execute(
        "SELECT ts, phase, summary FROM worklog WHERE job_id=? ORDER BY id DESC LIMIT 1",
        (job_id,),
    ).fetchone()
    return dict(row) if row else None
