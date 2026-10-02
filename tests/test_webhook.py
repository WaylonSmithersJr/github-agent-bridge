from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3

from fastapi.testclient import TestClient

from github_agent_bridge.backend import DashboardConfig, create_app


SECRET = "test-secret"


def signed_headers(payload: bytes, *, delivery: str = "delivery-1", event: str = "issue_comment") -> dict[str, str]:
    digest = hmac.new(SECRET.encode(), payload, hashlib.sha256).hexdigest()
    return {
        "content-type": "application/json",
        "x-github-delivery": delivery,
        "x-github-event": event,
        "x-hub-signature-256": f"sha256={digest}",
    }


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
