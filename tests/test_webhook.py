from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3

from fastapi.testclient import TestClient

from github_agent_bridge.backend import DashboardConfig, _encode_session, _sign, create_app


SECRET = "test-secret"


def signed_headers(payload: bytes, *, delivery: str = "delivery-1", event: str = "issue_comment", secret: str = SECRET) -> dict[str, str]:
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return {
        "content-type": "application/json",
        "x-github-delivery": delivery,
        "x-github-event": event,
        "x-hub-signature-256": f"sha256={digest}",
    }


def hook_headers(payload: bytes, *, delivery: str, event: str, hook_id: str) -> dict[str, str]:
    return {**signed_headers(payload, delivery=delivery, event=event), "x-github-hook-id": hook_id}


def issue_comment_payload(*, action: str = "created") -> bytes:
    return json.dumps({
        "action": action,
        "repository": {"full_name": "gisce/github-agent-bridge"},
        "comment": {"id": 5948901951},
    }).encode()


def test_webhook_shadow_verifies_and_persists_without_creating_job(tmp_path):
    db = tmp_path / "bridge.sqlite3"
    payload = issue_comment_payload()
    client = TestClient(create_app(DashboardConfig(db=db, require_auth=False, webhook_secrets=(SECRET,))))

    response = client.post("/api/webhooks/github", content=payload, headers=signed_headers(payload))

    assert response.status_code == 200
    assert response.json() == {
        "mode": "shadow",
        "status": "observed",
        "event_key": "issue_comment:created:gisce/github-agent-bridge:5948901951",
    }
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM github_events").fetchone()[0] == 0
        assert con.execute("SELECT payload_hash FROM webhook_shadow_receipts").fetchone()[0] == hashlib.sha256(payload).hexdigest()


def test_webhook_shadow_rejects_invalid_signature_without_persisting(tmp_path):
    db = tmp_path / "bridge.sqlite3"
    payload = issue_comment_payload()
    headers = signed_headers(payload)
    headers["x-hub-signature-256"] = "sha256=invalid"
    client = TestClient(create_app(DashboardConfig(db=db, require_auth=False, webhook_secrets=(SECRET,))))

    response = client.post("/api/webhooks/github", content=payload, headers=headers)

    assert response.status_code == 401
    assert not db.exists()


def test_webhook_shadow_deduplicates_delivery_and_tracks_edited_separately(tmp_path):
    db = tmp_path / "bridge.sqlite3"
    payload = issue_comment_payload(action="edited")
    client = TestClient(create_app(DashboardConfig(db=db, require_auth=False, webhook_secrets=(SECRET,))))

    first = client.post("/api/webhooks/github", content=payload, headers=signed_headers(payload))
    duplicate = client.post("/api/webhooks/github", content=payload, headers=signed_headers(payload))

    assert first.json()["event_key"] == "issue_comment:edited:gisce/github-agent-bridge:5948901951"
    assert duplicate.json()["status"] == "duplicate"
    status = client.get("/api/webhooks/github/status").json()
    assert status["receipts"] == {"observed": 1}
    assert status["duplicate_deliveries"] == 1
    assert status["cross_source_matches"] == 0


def test_webhook_shadow_accepts_previous_rotation_secret(tmp_path):
    payload = issue_comment_payload()
    client = TestClient(create_app(DashboardConfig(
        db=tmp_path / "bridge.sqlite3",
        require_auth=False,
        webhook_secrets=("new-secret", SECRET),
    )))

    assert client.post("/api/webhooks/github", content=payload, headers=signed_headers(payload)).status_code == 200


def test_webhook_shadow_selects_secret_by_repository_owner(tmp_path):
    payload = issue_comment_payload()
    client = TestClient(create_app(DashboardConfig(
        db=tmp_path / "bridge.sqlite3",
        require_auth=False,
        webhook_secrets_by_owner={"gisce": ("gisce-secret",), "example": ("example-secret",)},
    )))

    assert client.post(
        "/api/webhooks/github",
        content=payload,
        headers=signed_headers(payload, secret="gisce-secret"),
    ).status_code == 200
    assert client.post(
        "/api/webhooks/github",
        content=payload,
        headers=signed_headers(payload, delivery="wrong-owner-secret", secret="example-secret"),
    ).status_code == 401


def test_webhook_shadow_rejects_unconfigured_repository_owner(tmp_path):
    payload = json.dumps({
        "action": "created",
        "repository": {"full_name": "unknown/repository"},
        "comment": {"id": 1},
    }).encode()
    client = TestClient(create_app(DashboardConfig(
        db=tmp_path / "bridge.sqlite3",
        require_auth=False,
        webhook_secrets_by_owner={"gisce": (SECRET,)},
    )))

    response = client.post("/api/webhooks/github", content=payload, headers=signed_headers(payload))

    assert response.status_code == 403
    assert not (tmp_path / "bridge.sqlite3").exists()


def test_webhook_status_requires_dashboard_admin(tmp_path):
    config = DashboardConfig(
        db=tmp_path / "bridge.sqlite3",
        secret_key="dashboard-secret",
        allowed_users={"alice"},
        admin_users={"operator"},
        webhook_secrets=(SECRET,),
    )
    client = TestClient(create_app(config))

    assert client.get("/api/webhooks/github/status").status_code == 401
    client.cookies.set("gab_dashboard_session", _sign(config, _encode_session({"login": "alice"})))
    assert client.get("/api/webhooks/github/status").status_code == 403
    client.cookies.set("gab_dashboard_session", _sign(config, _encode_session({"login": "operator"}, is_admin=True)))
    assert client.get("/api/webhooks/github/status").status_code == 200
    assert client.get("/api/status").json()["webhook_configured"] is True


def test_dashboard_status_hides_webhook_tab_when_not_configured(tmp_path):
    client = TestClient(create_app(DashboardConfig(db=tmp_path / "bridge.sqlite3", require_auth=False)))

    assert client.get("/api/status").json()["webhook_configured"] is False


def test_webhook_status_exposes_real_hook_inventory_deliveries_and_timeseries(tmp_path):
    db = tmp_path / "bridge.sqlite3"
    client = TestClient(create_app(DashboardConfig(db=db, require_auth=False, webhook_secrets=(SECRET,))))
    ping = json.dumps({
        "zen": "Keep it logically awesome.",
        "hook": {"id": 42, "active": True, "events": ["issue_comment", "pull_request_review"]},
        "organization": {"login": "gisce"},
    }).encode()
    delivery = issue_comment_payload()

    assert client.post("/api/webhooks/github", content=ping, headers=hook_headers(ping, delivery="ping-1", event="ping", hook_id="42")).status_code == 200
    assert client.post("/api/webhooks/github", content=delivery, headers=hook_headers(delivery, delivery="delivery-1", event="issue_comment", hook_id="42")).status_code == 200
    response = client.get("/api/webhooks/github/status")

    assert response.status_code == 200
    status = response.json()
    assert status["hooks"] == [{
        "id": "42", "target": "gisce", "target_type": "organization",
        "active": True, "events": ["issue_comment", "pull_request_review"],
        "last_ping_at": status["hooks"][0]["last_ping_at"],
        "last_event_at": status["hooks"][0]["last_event_at"], "status": "receiving",
    }]
    assert status["hooks"][0]["last_ping_at"]
    assert status["hooks"][0]["last_event_at"]
    assert status["recent_deliveries"][0]["delivery_id"] == "delivery-1"
    assert status["recent_deliveries"][0]["hook_id"] == "42"
    assert status["timeseries"][0]["observed"] == 1
    assert status["timeseries"][0]["unsupported"] == 1


def test_webhook_receipt_retention_removes_expired_delivery_details(tmp_path):
    db = tmp_path / "bridge.sqlite3"
    client = TestClient(create_app(DashboardConfig(
        db=db, require_auth=False, webhook_secrets=(SECRET,), webhook_retention_days=7,
    )))
    payload = issue_comment_payload()
    client.post("/api/webhooks/github", content=payload, headers=signed_headers(payload, delivery="old"))
    with sqlite3.connect(db) as con:
        con.execute("UPDATE webhook_shadow_receipts SET created_at='2020-01-01T00:00:00+00:00'")
    client.post("/api/webhooks/github", content=payload, headers=signed_headers(payload, delivery="new"))

    assert [item["delivery_id"] for item in client.get("/api/webhooks/github/status").json()["recent_deliveries"]] == ["new"]


def test_existing_webhook_receipt_schema_is_migrated_for_hook_inventory(tmp_path):
    db = tmp_path / "bridge.sqlite3"
    with sqlite3.connect(db) as con:
        con.execute(
            "CREATE TABLE webhook_shadow_receipts (delivery_id TEXT PRIMARY KEY,event_name TEXT NOT NULL,"
            "action TEXT,event_key TEXT,repository TEXT,payload_hash TEXT NOT NULL,status TEXT NOT NULL,"
            "duplicate_count INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL)"
        )
    payload = issue_comment_payload()
    client = TestClient(create_app(DashboardConfig(db=db, require_auth=False, webhook_secrets=(SECRET,))))

    response = client.post(
        "/api/webhooks/github", content=payload,
        headers=hook_headers(payload, delivery="migrated", event="issue_comment", hook_id="84"),
    )

    assert response.status_code == 200
    assert client.get("/api/webhooks/github/status").json()["hooks"][0]["id"] == "84"


def test_submitted_review_uses_same_canonical_key_as_email_ingestion(tmp_path):
    payload = json.dumps({
        "action": "submitted",
        "repository": {"full_name": "gisce/github-agent-bridge"},
        "review": {"id": 1234},
    }).encode()
    client = TestClient(create_app(DashboardConfig(
        db=tmp_path / "bridge.sqlite3",
        require_auth=False,
        webhook_secrets=(SECRET,),
    )))

    response = client.post(
        "/api/webhooks/github",
        content=payload,
        headers=signed_headers(payload, event="pull_request_review"),
    )

    assert response.json()["event_key"] == "pull_request_review:created:gisce/github-agent-bridge:1234"
