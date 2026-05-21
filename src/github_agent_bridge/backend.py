from __future__ import annotations

import argparse
import json
import os
import secrets
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse

from .cli import DEFAULT_DB


DEFAULT_HOST = os.getenv("GITHUB_AGENT_BRIDGE_DASHBOARD_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.getenv("GITHUB_AGENT_BRIDGE_DASHBOARD_PORT", "8765"))
SESSION_COOKIE = "gab_dashboard_session"
OAUTH_STATE_COOKIE = "gab_dashboard_oauth_state"
GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"


class DashboardConfig:
    def __init__(
        self,
        *,
        db: str | Path = DEFAULT_DB,
        secret_key: str | None = None,
        oauth_client_id: str | None = None,
        oauth_client_secret: str | None = None,
        allowed_users: set[str] | None = None,
        allowed_orgs: set[str] | None = None,
        require_auth: bool = True,
    ) -> None:
        self.db = Path(db).expanduser()
        self.secret_key = secret_key or os.getenv("GITHUB_AGENT_BRIDGE_DASHBOARD_SECRET_KEY", "")
        self.oauth_client_id = oauth_client_id or os.getenv("GITHUB_OAUTH_CLIENT_ID", "")
        self.oauth_client_secret = oauth_client_secret or os.getenv("GITHUB_OAUTH_CLIENT_SECRET", "")
        self.allowed_users = allowed_users if allowed_users is not None else _csv_env("GITHUB_AGENT_BRIDGE_DASHBOARD_ALLOWED_USERS")
        self.allowed_orgs = allowed_orgs if allowed_orgs is not None else _csv_env("GITHUB_AGENT_BRIDGE_DASHBOARD_ALLOWED_ORGS")
        self.require_auth = require_auth

    @property
    def oauth_ready(self) -> bool:
        return bool(self.secret_key and self.oauth_client_id and self.oauth_client_secret)

    @property
    def has_authorization_policy(self) -> bool:
        return bool(self.allowed_users or self.allowed_orgs)


def _csv_env(name: str) -> set[str]:
    raw = os.getenv(name, "")
    return {part.strip().lower() for part in raw.split(",") if part.strip()}


def _readonly_connect(db: str | Path) -> sqlite3.Connection:
    path = Path(db).expanduser()
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    row = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
    return row is not None


def _parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _duration_seconds(start: str | None, end: str | None = None) -> int | None:
    started = _parse_utc(start)
    if started is None:
        return None
    finished = _parse_utc(end) or datetime.now(UTC)
    return max(0, int((finished - started).total_seconds()))


def _coerce_limit(value: int, maximum: int = 200) -> int:
    return max(1, min(value, maximum))


def _job_summary(row: sqlite3.Row) -> dict[str, Any]:
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
        "queue_wait_seconds": _duration_seconds(row["created_at"], row["started_at"]) if row["started_at"] else None,
        "runtime_seconds": _duration_seconds(row["started_at"], row["finished_at"]),
        "github_urls": context.get("urls", []),
    }


def _where(filters: dict[str, Any]) -> tuple[str, list[Any]]:
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
    with _readonly_connect(path) as con:
        if not _table_exists(con, "jobs"):
            return out | {"schema_ok": False}
        out["schema_ok"] = True
        counts = {r["status"]: int(r["count"]) for r in con.execute("SELECT status, count(*) count FROM jobs GROUP BY status")}
        out["counts"] = counts
        out.update(counts)
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
        out["running_jobs"] = [
            {
                "id": row["id"],
                "work_key": row["work_key"],
                "intent": row["work_intent"],
                "locked_by": row["locked_by"],
                "attempts": row["attempts"],
                "age_seconds": _duration_seconds(row["started_at"]),
                "idle_seconds": _duration_seconds(row["updated_at"]),
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
    where, args = _where(filters)
    if since:
        where += " AND created_at >= ?" if where else " WHERE created_at >= ?"
        args.append(since)
    if until:
        where += " AND created_at <= ?" if where else " WHERE created_at <= ?"
        args.append(until)
    args.append(_coerce_limit(limit))
    with _readonly_connect(path) as con:
        if not _table_exists(con, "jobs"):
            return []
        rows = con.execute(f"SELECT * FROM jobs{where} ORDER BY id DESC LIMIT ?", args).fetchall()
    return [_job_summary(row) for row in rows]


def get_job_detail(db: str | Path, job_id: int) -> dict[str, Any] | None:
    path = Path(db).expanduser()
    if not path.exists():
        return None
    with _readonly_connect(path) as con:
        if not _table_exists(con, "jobs"):
            return None
        row = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            return None
        job = _job_summary(row)
        job["context"] = json.loads(row["context_json"] or "{}")
        job["metadata"] = json.loads(row["metadata_json"] or "{}")
        job["worklog"] = [
            dict(log)
            for log in con.execute(
                "SELECT id, ts, phase, summary, detail FROM worklog WHERE job_id=? ORDER BY id",
                (job_id,),
            ).fetchall()
        ] if _table_exists(con, "worklog") else []
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
        ] if _table_exists(con, "coalesced_notifications") else []
    return job


def job_logs(db: str | Path, job_id: int, limit: int = 100) -> list[dict[str, Any]]:
    path = Path(db).expanduser()
    if not path.exists():
        return []
    with _readonly_connect(path) as con:
        if not _table_exists(con, "worklog"):
            return []
        rows = con.execute(
            "SELECT id, ts, phase, summary, detail FROM worklog WHERE job_id=? ORDER BY id DESC LIMIT ?",
            (job_id, _coerce_limit(limit, maximum=500)),
        ).fetchall()
    return [dict(row) for row in reversed(rows)]


def metrics_summary(db: str | Path) -> dict[str, Any]:
    path = Path(db).expanduser()
    if not path.exists():
        return {"db_exists": False, "status_counts": {}, "runtime_seconds": {}}
    with _readonly_connect(path) as con:
        if not _table_exists(con, "jobs"):
            return {"db_exists": True, "schema_ok": False, "status_counts": {}, "runtime_seconds": {}}
        rows = con.execute("SELECT status, repo, action, work_intent, created_at, started_at, finished_at FROM jobs").fetchall()
    status_counts = Counter(row["status"] for row in rows)
    by_repo = Counter(row["repo"] or "unknown" for row in rows)
    by_action = Counter(row["action"] for row in rows)
    by_intent = Counter(row["work_intent"] for row in rows)
    runtimes = sorted(
        seconds for seconds in (_duration_seconds(row["started_at"], row["finished_at"]) for row in rows if row["finished_at"]) if seconds is not None
    )
    waits = sorted(
        seconds for seconds in (_duration_seconds(row["created_at"], row["started_at"]) for row in rows if row["started_at"]) if seconds is not None
    )
    return {
        "db_exists": True,
        "schema_ok": True,
        "status_counts": dict(status_counts),
        "by_repo": dict(by_repo),
        "by_action": dict(by_action),
        "by_intent": dict(by_intent),
        "runtime_seconds": _percentiles(runtimes),
        "queue_wait_seconds": _percentiles(waits),
    }


def _percentiles(values: list[int]) -> dict[str, int | None]:
    if not values:
        return {"median": None, "p90": None, "p99": None}
    return {
        "median": _nearest_rank(values, 0.50),
        "p90": _nearest_rank(values, 0.90),
        "p99": _nearest_rank(values, 0.99),
    }


def _nearest_rank(values: list[int], percentile: float) -> int:
    index = max(0, min(len(values) - 1, int(round(percentile * (len(values) - 1)))))
    return values[index]


def _redacted_headers() -> dict[str, str]:
    return {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}


def _sign(config: DashboardConfig, value: str) -> str:
    import hmac
    import hashlib

    digest = hmac.new(config.secret_key.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{value}.{digest}"


def _unsign(config: DashboardConfig, value: str) -> str | None:
    import hmac

    try:
        raw, digest = value.rsplit(".", 1)
    except ValueError:
        return None
    expected = _sign(config, raw).rsplit(".", 1)[1]
    return raw if hmac.compare_digest(digest, expected) else None


def _github_json(url: str, token: str) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}", "User-Agent": "github-agent-bridge-dashboard"})
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _exchange_code(config: DashboardConfig, code: str) -> str:
    data = urllib.parse.urlencode({
        "client_id": config.oauth_client_id,
        "client_secret": config.oauth_client_secret,
        "code": code,
    }).encode("utf-8")
    req = urllib.request.Request(GITHUB_TOKEN_URL, data=data, headers={"Accept": "application/json", "User-Agent": "github-agent-bridge-dashboard"})
    with urllib.request.urlopen(req, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    token = payload.get("access_token")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="oauth_token_exchange_failed")
    return str(token)


def _is_allowed(config: DashboardConfig, login: str, token: str | None = None) -> bool:
    user = login.lower()
    if config.allowed_users and user in config.allowed_users:
        return True
    if config.allowed_orgs and token:
        try:
            orgs = _github_json("https://api.github.com/user/orgs", token)
        except (urllib.error.URLError, TimeoutError):
            return False
        return any(str(org.get("login", "")).lower() in config.allowed_orgs for org in orgs if isinstance(org, dict))
    return not config.has_authorization_policy


def create_app(config: DashboardConfig | None = None) -> FastAPI:
    config = config or DashboardConfig()
    app = FastAPI(title="GitHub Agent Bridge Dashboard API")
    app.state.dashboard_config = config

    async def current_user(request: Request) -> str:
        cfg: DashboardConfig = request.app.state.dashboard_config
        if not cfg.require_auth:
            return "test"
        signed = request.cookies.get(SESSION_COOKIE)
        if not signed or not cfg.secret_key:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not_authenticated")
        login = _unsign(cfg, signed)
        if not login:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not_authorized")
        return login

    @app.exception_handler(sqlite3.OperationalError)
    async def database_unavailable(_: Request, exc: sqlite3.OperationalError) -> JSONResponse:
        return JSONResponse({"error": "database_unavailable", "detail": str(exc)}, status_code=status.HTTP_503_SERVICE_UNAVAILABLE, headers=_redacted_headers())

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        metrics = inspect_db_read_only(config.db)
        return {
            "ok": bool(metrics.get("db_exists") and metrics.get("schema_ok", True)),
            "service": "github-agent-bridge-dashboard",
            "db_exists": bool(metrics.get("db_exists")),
            "schema_ok": bool(metrics.get("schema_ok", True)),
            "oauth_configured": config.oauth_ready,
            "read_only": True,
        }

    @app.get("/api/status")
    def api_status(_: str = Depends(current_user)) -> dict[str, Any]:
        return {"service": "github-agent-bridge-dashboard", "read_only": True, "metrics": inspect_db_read_only(config.db)}

    @app.get("/api/jobs")
    def api_jobs(
        _: str = Depends(current_user),
        status_filter: str | None = Query(default=None, alias="status"),
        repo: str | None = None,
        thread: int | None = None,
        action: str | None = None,
        intent: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        return {
            "jobs": list_jobs(
                config.db,
                status_filter=status_filter,
                repo=repo,
                thread=thread,
                action=action,
                intent=intent,
                since=since,
                until=until,
                limit=limit,
            )
        }

    @app.get("/api/jobs/{job_id}")
    def api_job(job_id: int, _: str = Depends(current_user)) -> dict[str, Any]:
        job = get_job_detail(config.db, job_id)
        if job is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job_not_found")
        return {"job": job}

    @app.get("/api/jobs/{job_id}/logs")
    def api_job_logs(job_id: int, limit: int = 100, _: str = Depends(current_user)) -> dict[str, Any]:
        return {"logs": job_logs(config.db, job_id, limit=limit)}

    @app.get("/api/jobs/{job_id}/session")
    def api_job_session(job_id: int, _: str = Depends(current_user)) -> dict[str, Any]:
        job = get_job_detail(config.db, job_id)
        if job is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job_not_found")
        return {"job_id": job_id, "session": None, "detail": "session correlation is not available in M1"}

    @app.get("/api/metrics/summary")
    def api_metrics(_: str = Depends(current_user)) -> dict[str, Any]:
        return {"metrics": metrics_summary(config.db)}

    @app.get("/api/processes")
    def api_processes(_: str = Depends(current_user)) -> dict[str, Any]:
        metrics = inspect_db_read_only(config.db)
        return {"processes": metrics.get("running_jobs", []), "detail": "runtime proc sampling is planned for M3"}

    @app.get("/api/alerts")
    def api_alerts(_: str = Depends(current_user)) -> dict[str, Any]:
        return {"alerts": [], "detail": "persistent alert storage is planned for M3"}

    @app.get("/api/events/stream")
    def api_events(_: str = Depends(current_user)) -> Response:
        return Response("event: ready\ndata: {}\n\n", media_type="text/event-stream", headers=_redacted_headers())

    @app.get("/auth/login")
    def login() -> RedirectResponse:
        if not config.oauth_ready:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="oauth_not_configured")
        state = secrets.token_urlsafe(24)
        params = urllib.parse.urlencode({"client_id": config.oauth_client_id, "scope": "read:user read:org", "state": state})
        response = RedirectResponse(f"{GITHUB_AUTHORIZE_URL}?{params}", status_code=status.HTTP_302_FOUND)
        response.set_cookie(OAUTH_STATE_COOKIE, _sign(config, state), httponly=True, secure=True, samesite="lax", max_age=600)
        return response

    @app.get("/auth/callback")
    def callback(code: str, state: str, request: Request) -> RedirectResponse:
        if not config.oauth_ready:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="oauth_not_configured")
        signed_state = request.cookies.get(OAUTH_STATE_COOKIE)
        if not signed_state or _unsign(config, signed_state) != state:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="oauth_state_mismatch")
        token = _exchange_code(config, code)
        user = _github_json(GITHUB_USER_URL, token)
        login = str(user.get("login", ""))
        if not login or not _is_allowed(config, login, token):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="not_authorized")
        response = RedirectResponse("/", status_code=status.HTTP_302_FOUND)
        response.set_cookie(SESSION_COOKIE, _sign(config, login.lower()), httponly=True, secure=True, samesite="lax")
        response.delete_cookie(OAUTH_STATE_COOKIE)
        return response

    return app


app = create_app()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=Path(sys.argv[0]).name)
    parser.add_argument("--db", default=os.getenv("GITHUB_AGENT_BRIDGE_DASHBOARD_DB", os.getenv("GITHUB_AGENT_BRIDGE_DB", DEFAULT_DB)))
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-auth", action="store_true", help="disable auth for isolated local development only")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        import uvicorn
    except ImportError:
        print("uvicorn is required; install github-agent-bridge[dashboard]", file=sys.stderr)
        return 2
    uvicorn.run(create_app(DashboardConfig(db=args.db, require_auth=not args.no_auth)), host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
