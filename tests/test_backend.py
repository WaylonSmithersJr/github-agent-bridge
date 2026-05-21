from __future__ import annotations

import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from github_agent_bridge.backend import list_jobs, make_server, status_payload
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


def test_backend_status_is_read_only_and_lists_recent_jobs(tmp_path):
    db = tmp_path / "bridge.sqlite3"
    q = JobQueue(db)
    q.enqueue(notif(), Policy(trusted_orgs=["gisce"]))

    payload = status_payload(db)

    assert payload["read_only"] is True
    assert payload["metrics"]["pending"] == 1
    assert payload["recent_jobs"][0]["work_key"] == "gisce/erp#1"


def test_backend_missing_db_does_not_create_database(tmp_path):
    db = tmp_path / "missing.sqlite3"

    payload = status_payload(db)

    assert payload["metrics"]["db_exists"] is False
    assert db.exists() is False


def test_backend_jobs_can_filter_by_status(tmp_path):
    db = tmp_path / "bridge.sqlite3"
    q = JobQueue(db)
    job, _ = q.enqueue(notif(), Policy(trusted_orgs=["gisce"]))
    q.finish(job.id, "blocked", "failed", "boom")

    assert [row["status"] for row in list_jobs(db, status="blocked")] == ["blocked"]
    assert list_jobs(db, status="pending") == []


def test_backend_http_endpoints_are_read_only(tmp_path):
    db = tmp_path / "bridge.sqlite3"
    JobQueue(db)
    server = make_server("127.0.0.1", 0, db)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"

    try:
        with urlopen(f"{base}/healthz") as response:
            assert json.loads(response.read().decode("utf-8"))["ok"] is True

        with urlopen(f"{base}/api/status") as response:
            assert json.loads(response.read().decode("utf-8"))["service"] == "github-agent-bridge-backend"

        request = Request(f"{base}/api/jobs", method="POST")
        try:
            urlopen(request)
        except HTTPError as exc:
            assert exc.code == 405
            assert json.loads(exc.read().decode("utf-8"))["error"] == "read_only"
        else:
            raise AssertionError("POST unexpectedly succeeded")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
