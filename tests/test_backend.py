from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from github_agent_bridge.backend import DashboardConfig, _encode_session, _sign, create_app
from github_agent_bridge.dashboard_data import get_job_detail, job_session, list_jobs, metrics_summary
from github_agent_bridge.monitor import MonitorReport
from github_agent_bridge.models import Notification
from github_agent_bridge.policy import Policy
from github_agent_bridge.queue import JobQueue


def notif(uid=1, mid="<1@github.com>", body="@pilipilisbot https://github.com/gisce/erp/pull/1#issuecomment-10"):
    return Notification(
        uid=uid,
        message_id=mid,
        subject="Re: [gisce/erp] thing (PR #1)",
        from_addr="GitHub <notifications@github.com>",
        body=body,
        auth={"spf": True, "dkim": True, "dmarc": True},
    )


def test_dashboard_status_is_read_only_and_lists_recent_jobs(tmp_path):
    db = tmp_path / "bridge.sqlite3"
    q = JobQueue(db)
    q.enqueue(notif(), Policy(trusted_orgs=["gisce"]))
    app = create_app(DashboardConfig(db=db, require_auth=False))

    client = TestClient(app)
    response = client.get("/api/status")
    jobs = client.get("/api/jobs")

    assert response.status_code == 200
    assert response.json()["read_only"] is True
    assert response.json()["metrics"]["pending"] == 1
    assert jobs.json()["jobs"][0]["work_key"] == "gisce/erp#1"


def test_dashboard_serves_built_react_ui_with_existing_auth(tmp_path):
    db = tmp_path / "bridge.sqlite3"
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<!doctype html><div id=\"root\"></div>", encoding="utf-8")
    q = JobQueue(db)
    q.enqueue(notif(), Policy(trusted_orgs=["gisce"]))
    app = create_app(DashboardConfig(db=db, static_dir=static_dir, require_auth=False))

    response = TestClient(app).get("/")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "root" in response.text


def test_dashboard_ui_requires_auth_by_default(tmp_path):
    db = tmp_path / "bridge.sqlite3"
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<!doctype html><div id=\"root\"></div>", encoding="utf-8")
    JobQueue(db)
    app = create_app(DashboardConfig(db=db, static_dir=static_dir, secret_key="secret", allowed_users={"alice"}))

    response = TestClient(app).get("/")

    assert response.status_code == 401


def test_dashboard_ui_reports_missing_build_after_auth(tmp_path):
    db = tmp_path / "bridge.sqlite3"
    JobQueue(db)
    app = create_app(DashboardConfig(db=db, static_dir=tmp_path / "missing-static", require_auth=False))

    response = TestClient(app).get("/")

    assert response.status_code == 503
    assert response.json()["detail"] == "dashboard_ui_not_built"


def test_dashboard_missing_db_does_not_create_database(tmp_path):
    db = tmp_path / "missing.sqlite3"
    app = create_app(DashboardConfig(db=db, require_auth=False))

    response = TestClient(app).get("/api/health")

    assert response.json()["db_exists"] is False
    assert db.exists() is False


def test_dashboard_jobs_can_filter_by_status_repo_action_and_intent(tmp_path):
    db = tmp_path / "bridge.sqlite3"
    q = JobQueue(db)
    job, _ = q.enqueue(notif(), Policy(trusted_orgs=["gisce"]))
    q.finish(job.id, "blocked", "failed", "boom")

    rows = list_jobs(db, status_filter="blocked", repo="gisce/erp", action="reply_comment", intent="review_only")

    assert [row["status"] for row in rows] == ["blocked"]
    assert list_jobs(db, status_filter="pending") == []


def test_dashboard_exposes_job_detail_logs_and_metrics(tmp_path):
    db = tmp_path / "bridge.sqlite3"
    q = JobQueue(db)
    job, _ = q.enqueue(notif(), Policy(trusted_orgs=["gisce"]))
    q.finish(job.id, "done", "completed")

    detail = get_job_detail(db, job.id)
    metrics = metrics_summary(db)
    client = TestClient(create_app(DashboardConfig(db=db, require_auth=False)))

    assert detail is not None
    assert detail["worklog"][0]["phase"] == "queued"
    assert metrics["status_counts"]["done"] == 1
    assert list(metrics["by_created_day"].values()) == [1]
    assert client.get(f"/api/jobs/{job.id}/logs").json()["logs"][-1]["phase"] == "done"
    assert client.get("/api/metrics/summary").json()["metrics"]["by_repo"]["gisce/erp"] == 1


def test_dashboard_exposes_safe_openclaw_session_correlation(tmp_path):
    db = tmp_path / "bridge.sqlite3"
    q = JobQueue(db)
    job, _ = q.enqueue(notif(), Policy(trusted_orgs=["gisce"]))
    claimed = q.claim_next("worker-1")
    assert claimed is not None

    session = job_session(db, job.id)
    client = TestClient(create_app(DashboardConfig(db=db, require_auth=False)))
    payload = client.get(f"/api/jobs/{job.id}/session").json()["session"]

    assert claimed.metadata["openclaw_session_id"] == f"github-agent-bridge-job-{job.id}"
    assert session is not None
    assert session["id"] == f"github-agent-bridge-job-{job.id}"
    assert session["transcript_exposure"] == "not_exposed"
    assert payload["id"] == session["id"]


def test_dashboard_requires_auth_by_default(tmp_path):
    db = tmp_path / "bridge.sqlite3"
    JobQueue(db)
    app = create_app(DashboardConfig(db=db, secret_key="secret", allowed_users={"alice"}))

    response = TestClient(app).get("/api/jobs")

    assert response.status_code == 401


def test_dashboard_session_authorization_allows_configured_user(tmp_path):
    db = tmp_path / "bridge.sqlite3"
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<!doctype html><div id=\"root\"></div>", encoding="utf-8")
    JobQueue(db)
    app = create_app(DashboardConfig(db=db, static_dir=static_dir, secret_key="secret", allowed_users={"alice"}))

    client = TestClient(app)
    client.cookies.set("gab_dashboard_session", _sign(app.state.dashboard_config, "alice"))

    assert client.get("/api/jobs").status_code == 200
    assert client.get("/").status_code == 200


def test_dashboard_me_exposes_safe_oauth_profile(tmp_path):
    db = tmp_path / "bridge.sqlite3"
    JobQueue(db)
    app = create_app(DashboardConfig(db=db, secret_key="secret", allowed_users={"alice"}))
    client = TestClient(app)
    client.cookies.set(
        "gab_dashboard_session",
        _sign(
            app.state.dashboard_config,
            _encode_session({"login": "Alice", "avatar_url": "https://avatars.githubusercontent.com/u/1?v=4", "html_url": "https://github.com/alice"}),
        ),
    )

    response = client.get("/api/me")

    assert response.status_code == 200
    assert response.json()["user"] == {
        "login": "alice",
        "avatar_url": "https://avatars.githubusercontent.com/u/1?v=4",
        "html_url": "https://github.com/alice",
    }


def test_dashboard_oauth_login_uses_minimal_scope_for_user_allowlist(tmp_path):
    db = tmp_path / "bridge.sqlite3"
    JobQueue(db)
    app = create_app(
        DashboardConfig(
            db=db,
            secret_key="secret",
            oauth_client_id="client-id",
            oauth_client_secret="client-secret",
            allowed_users={"alice"},
        )
    )

    response = TestClient(app, follow_redirects=False).get("/auth/login")

    assert response.status_code == 302
    query = parse_qs(urlparse(response.headers["location"]).query)
    assert query["scope"] == ["read:user"]


def test_dashboard_oauth_login_requests_org_scope_only_for_org_allowlist(tmp_path):
    db = tmp_path / "bridge.sqlite3"
    JobQueue(db)
    app = create_app(
        DashboardConfig(
            db=db,
            secret_key="secret",
            oauth_client_id="client-id",
            oauth_client_secret="client-secret",
            allowed_orgs={"example"},
        )
    )

    response = TestClient(app, follow_redirects=False).get("/auth/login")

    assert response.status_code == 302
    query = parse_qs(urlparse(response.headers["location"]).query)
    assert query["scope"] == ["read:user read:org"]


def test_dashboard_processes_exposes_live_executor_snapshot(tmp_path, monkeypatch):
    db = tmp_path / "bridge.sqlite3"
    q = JobQueue(db)
    q.enqueue(notif(), Policy(trusted_orgs=["gisce"]))
    q.claim_next("worker-1")

    def fake_monitor(_db):
        return MonitorReport(
            ok=True,
            metrics={
                "running_jobs": [{"id": 1, "work_key": "gisce/erp#1"}],
                "executor_service": "active",
                "executor_pid": 123,
                "executor_children": [
                    {
                        "pid": 456,
                        "ppid": 123,
                        "state": "S",
                        "cmd": "openclaw agent",
                        "cpu_ticks": 12,
                        "io_bytes": {"read_bytes": 100, "write_bytes": 50},
                        "children": [],
                    }
                ],
            },
        )

    monkeypatch.setattr("github_agent_bridge.backend.monitor", fake_monitor)
    client = TestClient(create_app(DashboardConfig(db=db, require_auth=False)))

    response = client.get("/api/processes")

    assert response.status_code == 200
    payload = response.json()
    assert payload["executor"]["service"] == "active"
    assert payload["executor"]["children"][0]["cpu_ticks"] == 12
