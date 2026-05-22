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
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .cli import DEFAULT_DB
from .dashboard_data import get_job_detail, inspect_db_read_only, job_logs, list_jobs, metrics_summary
from .monitor import monitor


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
        static_dir: str | Path | None = None,
    ) -> None:
        self.db = Path(db).expanduser()
        self.secret_key = secret_key or os.getenv("GITHUB_AGENT_BRIDGE_DASHBOARD_SECRET_KEY", "")
        self.oauth_client_id = oauth_client_id or os.getenv("GITHUB_OAUTH_CLIENT_ID", "")
        self.oauth_client_secret = oauth_client_secret or os.getenv("GITHUB_OAUTH_CLIENT_SECRET", "")
        self.allowed_users = allowed_users if allowed_users is not None else _csv_env("GITHUB_AGENT_BRIDGE_DASHBOARD_ALLOWED_USERS")
        self.allowed_orgs = allowed_orgs if allowed_orgs is not None else _csv_env("GITHUB_AGENT_BRIDGE_DASHBOARD_ALLOWED_ORGS")
        self.require_auth = require_auth
        self.static_dir = Path(static_dir or os.getenv("GITHUB_AGENT_BRIDGE_DASHBOARD_STATIC_DIR", Path(__file__).with_name("dashboard_static"))).expanduser()

    @property
    def oauth_ready(self) -> bool:
        return bool(self.secret_key and self.oauth_client_id and self.oauth_client_secret)

    @property
    def has_authorization_policy(self) -> bool:
        return bool(self.allowed_users or self.allowed_orgs)


def _csv_env(name: str) -> set[str]:
    raw = os.getenv(name, "")
    return {part.strip().lower() for part in raw.split(",") if part.strip()}


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
    assets_dir = config.static_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="dashboard-assets")

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

    @app.get("/")
    def dashboard(_: str = Depends(current_user)) -> FileResponse:
        index = config.static_dir / "index.html"
        if not index.exists():
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="dashboard_ui_not_built")
        return FileResponse(index, headers=_redacted_headers())

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
        report = monitor(config.db)
        metrics = report.metrics
        return {
            "running_jobs": metrics.get("running_jobs", []),
            "executor": {
                "service": metrics.get("executor_service", "unknown"),
                "pid": metrics.get("executor_pid"),
                "children": metrics.get("executor_children", []),
            },
            "alerts": report.alerts,
            "detail": "Live /proc snapshot; persistent process sample storage is planned for a later M3 increment.",
        }

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
        scopes = ["read:user"]
        if config.allowed_orgs:
            scopes.append("read:org")
        params = urllib.parse.urlencode({"client_id": config.oauth_client_id, "scope": " ".join(scopes), "state": state})
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
