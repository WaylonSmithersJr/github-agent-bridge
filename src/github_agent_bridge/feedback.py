from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from .models import GitHubContext, Notification, utc_now


ACTIONABLE_FEEDBACK_ACTIONS = {"reply_comment", "open_issue", "submit_review", "docs_update", "content_change"}
FEEDBACK_DECISIONS = {"auto_trusted", "ask"}


def compact(text: str, limit: int = 1600) -> str:
    clean = re.sub(r"\s+", " ", text or "").strip()
    if len(clean) <= limit:
        return clean
    return clean[: limit - 3].rstrip() + "..."


def short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def event_id(n: Notification) -> str:
    seed = n.message_id or f"{n.uid}:{n.subject}:{n.received_at}"
    return "github-agent-bridge-" + uuid.uuid5(uuid.NAMESPACE_URL, seed).hex[:16]


def canonical_key(scope: str, rule_type: str, rule: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", f"{scope}:{rule_type}:{rule}".lower()).strip("-")
    return short_hash(normalized)


def _connect(db_path: str | Path) -> sqlite3.Connection:
    con = sqlite3.connect(db_path, timeout=30, isolation_level=None)
    con.row_factory = sqlite3.Row
    return con


def capture_feedback(db_path: str | Path, n: Notification, ctx: GitHubContext, action: str, decision: str, work_intent: str) -> bool:
    """Capture feedback candidates into bridge-owned storage.

    This deliberately does not synthesize rules. The bridge records auditable
    evidence; only curated rows in feedback_rules are injected into agents.
    """
    if decision not in FEEDBACK_DECISIONS or action not in ACTIONABLE_FEEDBACK_ACTIONS:
        return False

    repo = ctx.repo or "unknown/repo"
    scope = f"repo:{repo}" if repo != "unknown/repo" else "github"
    context = {
        "subject": n.subject,
        "bridge_action": action,
        "decision": decision,
        "work_intent": work_intent,
        "work_key": ctx.work_key,
        "message_id": n.message_id,
        "uid": n.uid,
    }

    try:
        with _connect(db_path) as con:
            con.execute(
                """INSERT OR IGNORE INTO feedback_events(
                    id, occurred_at, captured_at, source, scope, actor, comment, context_json,
                    classification, confidence, memorable
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    event_id(n),
                    n.received_at,
                    utc_now(),
                    "github-agent-bridge",
                    scope,
                    "github",
                    compact(f"{n.subject}\n\n{n.body}"),
                    json.dumps(context, ensure_ascii=False, sort_keys=True),
                    "unreviewed",
                    0.0,
                    0,
                ),
            )
    except sqlite3.Error:
        return False
    return True


def add_rule(
    db_path: str | Path,
    scope: str,
    rule_type: str,
    rule: str,
    confidence: float,
    source_events: list[str] | None = None,
) -> dict[str, Any]:
    if not 0 <= confidence <= 1:
        raise ValueError("confidence must be between 0 and 1")
    clean_rule = compact(rule, 600)
    if not scope.strip():
        raise ValueError("scope is required")
    if not rule_type.strip():
        raise ValueError("rule type is required")
    if not clean_rule:
        raise ValueError("rule is required")

    now = utc_now()
    rule_id = canonical_key(scope, rule_type, clean_rule)
    events = sorted(set(source_events or []))
    with _connect(db_path) as con:
        row = con.execute("SELECT * FROM feedback_rules WHERE id=?", (rule_id,)).fetchone()
        if row:
            events = sorted(set(json.loads(row["source_events_json"] or "[]") + events))
            confidence = max(float(row["confidence"]), confidence)
            observations = int(row["observations"]) + 1
            con.execute(
                """UPDATE feedback_rules
                SET confidence=?, last_seen=?, source_events_json=?, observations=?
                WHERE id=?""",
                (confidence, now, json.dumps(events, ensure_ascii=False, sort_keys=True), observations, rule_id),
            )
        else:
            con.execute(
                """INSERT INTO feedback_rules(
                    id, scope, type, confidence, rule, created_at, last_seen, source_events_json, observations
                ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (rule_id, scope, rule_type, confidence, clean_rule, now, now, json.dumps(events, ensure_ascii=False, sort_keys=True), 1),
            )
    return next(rule for rule in list_rules(db_path, scope=scope, min_confidence=0) if rule["id"] == rule_id)


def list_events(db_path: str | Path, scope: str = "", limit: int = 20) -> list[dict[str, Any]]:
    clauses = []
    args: list[Any] = []
    if scope:
        clauses.append("(scope=? OR scope LIKE ?)")
        args.extend([scope, f"{scope}:%"])
    sql = "SELECT * FROM feedback_events"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY occurred_at DESC, id DESC LIMIT ?"
    args.append(limit)
    with _connect(db_path) as con:
        return [
            {
                "id": row["id"],
                "occurred_at": row["occurred_at"],
                "captured_at": row["captured_at"],
                "source": row["source"],
                "scope": row["scope"],
                "actor": row["actor"],
                "comment": row["comment"],
                "context": json.loads(row["context_json"] or "{}"),
                "classification": row["classification"],
                "confidence": row["confidence"],
                "memorable": bool(row["memorable"]),
            }
            for row in con.execute(sql, args)
        ]


def list_rules(db_path: str | Path, scope: str = "", min_confidence: float | None = None) -> list[dict[str, Any]]:
    clauses = []
    args: list[Any] = []
    if scope:
        clauses.append("(scope=? OR scope LIKE ?)")
        args.extend([scope, f"{scope}:%"])
    if min_confidence is not None:
        clauses.append("confidence>=?")
        args.append(min_confidence)
    sql = "SELECT * FROM feedback_rules"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY scope, type, rule"
    with _connect(db_path) as con:
        return [
            {
                "id": row["id"],
                "scope": row["scope"],
                "type": row["type"],
                "confidence": row["confidence"],
                "rule": row["rule"],
                "created_at": row["created_at"],
                "last_seen": row["last_seen"],
                "source_events": json.loads(row["source_events_json"] or "[]"),
                "observations": row["observations"],
            }
            for row in con.execute(sql, args)
        ]
