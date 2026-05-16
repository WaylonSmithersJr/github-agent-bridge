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

NOISE_RE = re.compile(r"^(ok|thanks|thank you|gr[aà]cies|merci|perfecte|fet|👍|👌|✅)[.! ]*$", re.I)

TYPE_KEYWORDS = {
    "style_preference": [
        "massa llarg",
        "massa curt",
        r"\bto\b",
        "canya",
        "robotic",
        "rob[oò]tic",
        r"\bia\b|intel.?lig[eè]ncia artificial",
        "natural",
        "directe",
        "telegr[aà]fic",
        "redacci[oó]",
    ],
    "operating_rule": [
        "sempre",
        "mai",
        "no facis",
        "evita",
        "quan ",
        "si ",
        "fes-ho",
        "respon",
        "abans de",
        "despr[eé]s",
    ],
    "agent_error": [
        "malament",
        "error",
        "fall",
        "bug",
        "trencat",
        "no funciona",
        "incorrecte",
    ],
    "technical_criterion": [
        "arquitectura",
        "test",
        "deploy",
        "seguretat",
        "api",
        "schema",
        "migraci[oó]",
        "performance",
        "refactor",
    ],
}


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


def classify(comment: str) -> tuple[str, float, bool]:
    lower = comment.lower().strip()
    if not lower or NOISE_RE.match(lower):
        return "noise", 0.05, False

    scores: dict[str, int] = {}
    for kind, patterns in TYPE_KEYWORDS.items():
        for pattern in patterns:
            if re.search(pattern, lower):
                scores[kind] = scores.get(kind, 0) + 1

    if not scores:
        return "domain_context", 0.35, False

    kind = max(scores, key=scores.get)
    confidence = min(0.9, 0.45 + (scores[kind] * 0.15))
    if kind == "operating_rule":
        confidence = max(confidence, 0.7)
    return kind, confidence, True


def synthesize_rule(comment: str, kind: str) -> str:
    lower = comment.lower()
    if "ia" in lower or "robot" in lower or "robò" in lower or "robo" in lower:
        return "Avoid AI-sounding or robotic prose; write direct, concrete text in the established voice."
    if "massa llarg" in lower:
        return "Keep responses compact; lead with the useful result and trim explanation unless it changes the decision."
    if "canya" in lower or "directe" in lower:
        return "Use a direct, opinionated style with clear trade-offs and minimal filler."
    if "ack" in lower or "👀" in comment or "respon" in lower:
        return "Avoid empty acknowledgements; respond with results, specific questions, or explicit blockers."
    if kind == "operating_rule":
        return compact(comment, 260)
    if kind == "agent_error":
        return "When a similar situation appears, check this prior failure before repeating the same action: " + compact(comment, 180)
    if kind == "technical_criterion":
        return "Respect this technical criterion in the scoped project: " + compact(comment, 190)
    return "Remember this scoped context: " + compact(comment, 200)


def canonical_key(scope: str, kind: str, rule: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", f"{scope}:{kind}:{rule}".lower()).strip("-")
    return short_hash(normalized)


def _connect(db_path: str | Path) -> sqlite3.Connection:
    con = sqlite3.connect(db_path, timeout=30, isolation_level=None)
    con.row_factory = sqlite3.Row
    return con


def capture_feedback(db_path: str | Path, n: Notification, ctx: GitHubContext, action: str, decision: str, work_intent: str) -> bool:
    """Capture feedback-like GitHub notifications into bridge-owned storage.

    Capture is best-effort. It must never block durable queueing of GitHub work.
    """
    if decision not in FEEDBACK_DECISIONS or action not in ACTIONABLE_FEEDBACK_ACTIONS:
        return False

    comment = compact(f"{n.subject}\n\n{n.body}")
    kind, confidence, memorable = classify(comment)
    rule_text = synthesize_rule(comment, kind) if memorable else ""
    repo = ctx.repo or "unknown/repo"
    scope = f"repo:{repo}" if repo != "unknown/repo" else "github"
    now = utc_now()
    event = {
        "subject": n.subject,
        "context": f"GitHub bridge {action}/{decision}; work_intent={work_intent}; thread={ctx.work_key}",
        "message_id": n.message_id,
        "uid": n.uid,
    }
    eid = event_id(n)

    try:
        with _connect(db_path) as con:
            con.execute("BEGIN IMMEDIATE")
            existing = con.execute("SELECT id FROM feedback_events WHERE id=?", (eid,)).fetchone()
            con.execute(
                """INSERT OR IGNORE INTO feedback_events(
                    id, occurred_at, captured_at, source, scope, actor, comment, context_json,
                    classification, confidence, memorable
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    eid,
                    n.received_at,
                    now,
                    "github-agent-bridge",
                    scope,
                    "github",
                    comment,
                    json.dumps(event, ensure_ascii=False, sort_keys=True),
                    kind,
                    confidence,
                    1 if memorable else 0,
                ),
            )
            if memorable:
                rule_id = canonical_key(scope, kind, rule_text)
                row = con.execute("SELECT * FROM feedback_rules WHERE id=?", (rule_id,)).fetchone()
                if row:
                    events = sorted(set(json.loads(row["source_events_json"] or "[]") + [eid]))
                    observations = int(row["observations"]) + (0 if existing else 1)
                    updated_confidence = min(0.98, max(float(row["confidence"]), confidence) + (0 if existing else 0.05))
                    con.execute(
                        """UPDATE feedback_rules
                        SET last_seen=?, source_events_json=?, observations=?, confidence=?
                        WHERE id=?""",
                        (n.received_at, json.dumps(events, ensure_ascii=False, sort_keys=True), observations, updated_confidence, rule_id),
                    )
                else:
                    con.execute(
                        """INSERT INTO feedback_rules(
                            id, scope, type, confidence, rule, created_at, last_seen, source_events_json, observations
                        ) VALUES(?,?,?,?,?,?,?,?,?)""",
                        (rule_id, scope, kind, confidence, rule_text, n.received_at, n.received_at, json.dumps([eid]), 1),
                    )
            con.commit()
    except sqlite3.Error:
        return False
    return memorable


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

