from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import utc_now


@dataclass(frozen=True)
class ShadowReceipt:
    delivery_id: str
    event_name: str
    action: str | None
    event_key: str | None
    repository: str | None
    status: str


def verify_signature(payload: bytes, signature: str, secrets: tuple[str, ...]) -> bool:
    if not signature.startswith("sha256=") or not secrets:
        return False
    supplied = signature.removeprefix("sha256=")
    return any(
        hmac.compare_digest(
            hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest(),
            supplied,
        )
        for secret in secrets
    )


def canonical_webhook_event_key(event_name: str, payload: dict[str, Any]) -> str | None:
    action = str(payload.get("action") or "")
    repository = payload.get("repository") or {}
    repo = str(repository.get("full_name") or "").lower()
    if not repo:
        return None
    objects = {
        "issue_comment": "comment",
        "pull_request_review_comment": "comment",
        "pull_request_review": "review",
        "commit_comment": "comment",
    }
    object_name = objects.get(event_name)
    target = payload.get(object_name) if object_name else None
    target_id = target.get("id") if isinstance(target, dict) else None
    if target_id and action:
        canonical_action = "created" if action in {"created", "submitted"} else action
        return f"{event_name}:{canonical_action}:{repo}:{target_id}"
    if event_name == "workflow_run":
        run = payload.get("workflow_run") or {}
        run_id = run.get("id")
        if run_id and action:
            return f"workflow_run:{action}:{repo}:{run_id}"
    return None


def persist_shadow_delivery(
    db: str | Path,
    *,
    delivery_id: str,
    event_name: str,
    raw_payload: bytes,
) -> ShadowReceipt:
    payload = json.loads(raw_payload)
    action = str(payload.get("action") or "") or None
    repository = payload.get("repository") or {}
    repo = str(repository.get("full_name") or "") or None
    event_key = canonical_webhook_event_key(event_name, payload)
    status = "observed" if event_key else "unsupported"
    payload_hash = hashlib.sha256(raw_payload).hexdigest()
    now = utc_now()
    con = sqlite3.connect(Path(db).expanduser(), timeout=30)
    try:
        try:
            con.execute(
                "INSERT INTO webhook_shadow_receipts(delivery_id,event_name,action,event_key,repository,payload_hash,status,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (delivery_id, event_name, action, event_key, repo, payload_hash, status, now),
            )
            con.commit()
        except sqlite3.IntegrityError:
            con.rollback()
            con.execute(
                "UPDATE webhook_shadow_receipts SET duplicate_count=duplicate_count+1 WHERE delivery_id=?",
                (delivery_id,),
            )
            con.commit()
            status = "duplicate"
    finally:
        con.close()
    return ShadowReceipt(delivery_id, event_name, action, event_key, repo, status)
