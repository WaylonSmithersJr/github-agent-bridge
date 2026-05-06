from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import GitHubContext, Job, Notification, utc_now
from .parser import classify_github_action, classify_work_intent, extract_github_context
from .policy import Policy

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  work_key TEXT NOT NULL,
  repo TEXT,
  thread INTEGER,
  status TEXT NOT NULL CHECK(status IN ('pending','running','done','blocked','denied','waiting_approval')),
  action TEXT NOT NULL,
  decision TEXT NOT NULL,
  work_intent TEXT NOT NULL,
  subject TEXT NOT NULL,
  message_id TEXT NOT NULL UNIQUE,
  uid INTEGER,
  context_json TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  attempts INTEGER NOT NULL DEFAULT 0,
  coalesced_count INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  locked_by TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_status_created ON jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_work_status ON jobs(work_key, status);
CREATE TABLE IF NOT EXISTS coalesced_notifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  uid INTEGER,
  message_id TEXT NOT NULL UNIQUE,
  subject TEXT NOT NULL,
  context_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS worklog (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  job_id INTEGER,
  work_key TEXT,
  phase TEXT NOT NULL,
  summary TEXT NOT NULL,
  detail TEXT
);
"""
ACTIVE_STATUSES = ("pending", "running", "waiting_approval")


class JobQueue:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init()

    def connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        return con

    def init(self) -> None:
        with self.connect() as con:
            con.executescript(SCHEMA)

    def enqueue(self, n: Notification, policy: Policy) -> tuple[Job | None, str]:
        ctx = extract_github_context(n.body)
        action = classify_github_action(n.subject, n.body)
        intent = classify_work_intent(n.subject, n.body)
        decision = policy.decision(n, ctx, action)
        status = {"auto": "done", "ask": "waiting_approval", "deny": "denied"}.get(decision, "pending")
        now = utc_now()
        metadata = {"received_at": n.received_at}
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            try:
                existing = con.execute(
                    f"SELECT * FROM jobs WHERE work_key=? AND status IN ({','.join('?' for _ in ACTIVE_STATUSES)}) ORDER BY id LIMIT 1",
                    (ctx.work_key, *ACTIVE_STATUSES),
                ).fetchone()
                if existing and decision == "auto_trusted":
                    con.execute("INSERT OR IGNORE INTO coalesced_notifications(job_id,uid,message_id,subject,context_json,created_at) VALUES(?,?,?,?,?,?)", (existing["id"], n.uid, n.message_id, n.subject, ctx.to_json(), now))
                    con.execute("UPDATE jobs SET coalesced_count=coalesced_count+1, uid=?, message_id=message_id, subject=?, context_json=?, updated_at=? WHERE id=?", (n.uid, n.subject, ctx.to_json(), now, existing["id"]))
                    self._log(con, existing["id"], ctx.work_key, "coalesced", "Notification coalesced into active job", n.message_id)
                    con.commit()
                    return self._row_to_job(existing), "coalesced"
                con.execute(
                    "INSERT INTO jobs(work_key,repo,thread,status,action,decision,work_intent,subject,message_id,uid,context_json,metadata_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (ctx.work_key, ctx.repo, ctx.issue_number, status, action, decision, intent, n.subject, n.message_id, n.uid, ctx.to_json(), json.dumps(metadata), now, now),
                )
                job_id = int(con.execute("SELECT last_insert_rowid()").fetchone()[0])
                self._log(con, job_id, ctx.work_key, "queued" if status == "pending" else status, f"decision={decision} action={action}", n.message_id)
                con.commit()
                return self.get(job_id), "enqueued"
            except sqlite3.IntegrityError:
                con.rollback()
                row = con.execute("SELECT * FROM jobs WHERE message_id=?", (n.message_id,)).fetchone()
                return self._row_to_job(row) if row else None, "duplicate"

    def claim_next(self, worker_id: str) -> Job | None:
        now = utc_now()
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute(
                """SELECT * FROM jobs j WHERE j.status='pending'
                AND NOT EXISTS (SELECT 1 FROM jobs r WHERE r.work_key=j.work_key AND r.status='running')
                ORDER BY j.created_at LIMIT 1"""
            ).fetchone()
            if not row:
                con.commit(); return None
            con.execute("UPDATE jobs SET status='running', locked_by=?, attempts=attempts+1, started_at=?, updated_at=? WHERE id=?", (worker_id, now, now, row["id"]))
            self._log(con, row["id"], row["work_key"], "running", f"claimed by {worker_id}", None)
            con.commit()
            return self.get(int(row["id"]))

    def finish(self, job_id: int, status: str, summary: str, detail: str | None = None) -> None:
        now = utc_now()
        with self.connect() as con:
            con.execute("UPDATE jobs SET status=?, last_error=?, locked_by=NULL, finished_at=?, updated_at=? WHERE id=?", (status, detail if status == "blocked" else None, now, now, job_id))
            row = con.execute("SELECT work_key FROM jobs WHERE id=?", (job_id,)).fetchone()
            self._log(con, job_id, row["work_key"] if row else None, status, summary, detail)

    def get(self, job_id: int) -> Job | None:
        with self.connect() as con:
            return self._row_to_job(con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())

    def stats(self) -> dict[str, int]:
        with self.connect() as con:
            return {r["status"]: r["count"] for r in con.execute("SELECT status, count(*) count FROM jobs GROUP BY status")}

    def pending_age_seconds(self) -> int | None:
        with self.connect() as con:
            row = con.execute("SELECT CAST((julianday('now') - julianday(min(created_at))) * 86400 AS INTEGER) age FROM jobs WHERE status='pending'").fetchone()
            return None if row is None or row["age"] is None else int(row["age"])

    def set_state(self, key: str, value: str) -> None:
        with self.connect() as con:
            con.execute("INSERT INTO state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    def get_state(self, key: str, default: str = "") -> str:
        with self.connect() as con:
            row = con.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
            return row["value"] if row else default

    def _log(self, con: sqlite3.Connection, job_id: int | None, work_key: str | None, phase: str, summary: str, detail: str | None) -> None:
        con.execute("INSERT INTO worklog(ts,job_id,work_key,phase,summary,detail) VALUES(?,?,?,?,?,?)", (utc_now(), job_id, work_key, phase, summary, detail))

    def _row_to_job(self, row: sqlite3.Row | None) -> Job | None:
        if row is None:
            return None
        return Job(id=row["id"], work_key=row["work_key"], repo=row["repo"], thread=row["thread"], status=row["status"], action=row["action"], work_intent=row["work_intent"], subject=row["subject"], message_id=row["message_id"], uid=row["uid"], context=GitHubContext.from_json(row["context_json"]), attempts=row["attempts"], coalesced_count=row["coalesced_count"], last_error=row["last_error"], locked_by=row["locked_by"], created_at=row["created_at"], updated_at=row["updated_at"], metadata=json.loads(row["metadata_json"] or "{}"))
