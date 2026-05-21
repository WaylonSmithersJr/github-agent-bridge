from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .cli import DEFAULT_DB


DEFAULT_HOST = os.getenv("GITHUB_AGENT_BRIDGE_BACKEND_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.getenv("GITHUB_AGENT_BRIDGE_BACKEND_PORT", "8765"))


def _json_response(handler: BaseHTTPRequestHandler, status: HTTPStatus, payload: dict[str, Any] | list[Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    handler.send_response(status.value)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _text_response(handler: BaseHTTPRequestHandler, status: HTTPStatus, body: str) -> None:
    raw = body.encode("utf-8")
    handler.send_response(status.value)
    handler.send_header("Content-Type", "text/plain; charset=utf-8")
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)


def _readonly_connect(db: str | Path) -> sqlite3.Connection:
    path = Path(db).expanduser()
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _coerce_limit(raw: str | None, default: int = 20, maximum: int = 200) -> int:
    try:
        value = int(raw or default)
    except ValueError:
        return default
    return max(1, min(value, maximum))


def list_jobs(db: str | Path, status: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    path = Path(db).expanduser()
    if not path.exists():
        return []
    sql = """
        SELECT id, work_key, repo, thread, status, action, decision, work_intent,
               subject, attempts, coalesced_count, last_error, locked_by,
               created_at, updated_at, started_at, finished_at
        FROM jobs
    """
    args: list[Any] = []
    if status:
        sql += " WHERE status=?"
        args.append(status)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    with _readonly_connect(path) as con:
        rows = con.execute(sql, args).fetchall()
    return [dict(row) for row in rows]


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    row = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
    return row is not None


def inspect_db_read_only(db: str | Path) -> dict[str, Any]:
    path = Path(db).expanduser()
    out: dict[str, Any] = {"db_path": str(path), "db_exists": path.exists()}
    if not path.exists():
        return out
    with _readonly_connect(path) as con:
        if not _table_exists(con, "jobs"):
            return out | {"schema_ok": False}
        out["schema_ok"] = True
        stats = {r["status"]: int(r["count"]) for r in con.execute("SELECT status, count(*) count FROM jobs GROUP BY status")}
        out.update(stats)
        pending_age = con.execute("SELECT CAST((julianday('now') - julianday(min(created_at))) * 86400 AS INTEGER) age FROM jobs WHERE status='pending'").fetchone()["age"]
        out["oldest_pending_age_seconds"] = None if pending_age is None else int(pending_age)
        if _table_exists(con, "state"):
            state = {r["key"]: r["value"] for r in con.execute("SELECT key,value FROM state")}
            out["last_uid"] = state.get("last_uid")
        if _table_exists(con, "worklog"):
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
        out["running_jobs"] = [dict(row) for row in running_rows]
        out["running"] = len(running_rows)
    return out


def status_payload(db: str | Path, job_limit: int = 10) -> dict[str, Any]:
    metrics = inspect_db_read_only(db)
    return {
        "service": "github-agent-bridge-backend",
        "read_only": True,
        "metrics": metrics,
        "recent_jobs": list_jobs(db, limit=job_limit) if metrics.get("schema_ok") else [],
    }


class BackendHandler(BaseHTTPRequestHandler):
    server_version = "GitHubAgentBridgeBackend/0"

    @property
    def db_path(self) -> str:
        return self.server.db_path  # type: ignore[attr-defined]

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        try:
            if parsed.path == "/":
                _text_response(self, HTTPStatus.OK, "github-agent-bridge backend\n\nGET /healthz\nGET /api/status\nGET /api/jobs?status=pending&limit=20\n")
                return
            if parsed.path == "/healthz":
                metrics = inspect_db_read_only(self.db_path)
                _json_response(self, HTTPStatus.OK, {
                    "ok": bool(metrics.get("db_exists") and metrics.get("schema_ok", True)),
                    "db_exists": bool(metrics.get("db_exists")),
                    "schema_ok": bool(metrics.get("schema_ok", True)),
                })
                return
            if parsed.path == "/api/status":
                limit = _coerce_limit(params.get("limit", [None])[0], default=10)
                _json_response(self, HTTPStatus.OK, status_payload(self.db_path, job_limit=limit))
                return
            if parsed.path == "/api/jobs":
                status = params.get("status", [None])[0] or None
                limit = _coerce_limit(params.get("limit", [None])[0])
                _json_response(self, HTTPStatus.OK, {"jobs": list_jobs(self.db_path, status=status, limit=limit)})
                return
            _json_response(self, HTTPStatus.NOT_FOUND, {"error": "not_found"})
        except sqlite3.OperationalError as exc:
            _json_response(self, HTTPStatus.SERVICE_UNAVAILABLE, {"error": "database_unavailable", "detail": str(exc)})

    def do_POST(self) -> None:
        _json_response(self, HTTPStatus.METHOD_NOT_ALLOWED, {"error": "read_only"})

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write(f"{self.address_string()} - {fmt % args}\n")


def make_server(host: str, port: int, db: str | Path) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), BackendHandler)
    server.db_path = str(Path(db).expanduser())  # type: ignore[attr-defined]
    return server


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=Path(sys.argv[0]).name)
    parser.add_argument("--db", default=os.getenv("GITHUB_AGENT_BRIDGE_DB", DEFAULT_DB))
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    server = make_server(args.host, args.port, args.db)
    print(f"github-agent-bridge-backend listening on http://{args.host}:{args.port} db={Path(args.db).expanduser()}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
