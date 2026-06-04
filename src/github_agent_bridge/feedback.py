from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import subprocess
import uuid
from importlib import resources
from pathlib import Path
from typing import Any

from .models import GitHubContext, Notification, utc_now
from .parser import extract_github_context
from .policy import Policy


ACTIONABLE_FEEDBACK_ACTIONS = {"reply_comment", "open_issue", "submit_review", "docs_update", "content_change"}
FEEDBACK_DECISIONS = {"auto_trusted", "ask"}
PROMPT_RULES_PACKAGE = "github_agent_bridge.prompt_rules"


def load_prompt_rule(name: str) -> str:
    return resources.files(PROMPT_RULES_PACKAGE).joinpath(name).read_text(encoding="utf-8").strip() + "\n"


def load_prompt_override(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8").strip() + "\n"


FEEDBACK_CLASSIFIER_PROMPT = load_prompt_rule("feedback_classifier.md")


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


def pending_events(db_path: str | Path, scope: str = "", limit: int = 10) -> list[dict[str, Any]]:
    clauses = ["NOT EXISTS (SELECT 1 FROM feedback_rule_proposals p WHERE p.event_id=feedback_events.id)"]
    args: list[Any] = []
    if scope:
        clauses.append("(scope=? OR scope LIKE ?)")
        args.extend([scope, f"{scope}:%"])
    sql = "SELECT * FROM feedback_events WHERE " + " AND ".join(clauses) + " ORDER BY occurred_at ASC, id ASC LIMIT ?"
    args.append(limit)
    with _connect(db_path) as con:
        return [_event_dict(row) for row in con.execute(sql, args)]


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


def proposal_id(event_id: str, scope: str, rule_type: str, rule: str) -> str:
    return "feedback-proposal-" + canonical_key(event_id, rule_type, f"{scope}:{rule}")


def _extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("{"):
        return json.loads(stripped)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("LLM output did not contain a JSON object")
    return json.loads(stripped[start : end + 1])


def _openclaw_text_from_json(raw: str) -> str:
    data = json.loads(raw)
    for key in ("message", "reply", "text", "content", "output"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value
    if isinstance(data.get("result"), dict):
        payloads = data["result"].get("payloads")
        if isinstance(payloads, list):
            for payload in payloads:
                if isinstance(payload, dict) and isinstance(payload.get("text"), str) and payload["text"].strip():
                    return payload["text"]
        for key in ("message", "reply", "text", "content", "output"):
            value = data["result"].get(key)
            if isinstance(value, str) and value.strip():
                return value
    return raw


def build_learning_prompt(event: dict[str, Any], prompt_template: str | None = None) -> str:
    template = prompt_template or FEEDBACK_CLASSIFIER_PROMPT
    return template.format(event_json=json.dumps(event, ensure_ascii=False, sort_keys=True))


def repo_from_event_scope(event: dict[str, Any]) -> str | None:
    scope = str(event.get("scope") or "")
    if not scope.startswith("repo:"):
        return None
    repo = scope.removeprefix("repo:").strip().lower()
    return repo or None


def route_agent_for_event(event: dict[str, Any], policy: Policy | None = None) -> str | None:
    repo = repo_from_event_scope(event)
    if not repo or not policy:
        return None
    return policy.route_for(repo).agent


def is_model_override_not_allowed(exc: Exception) -> bool:
    message = str(exc)
    return "Model override" in message and "not allowed" in message


def session_id_for_agent(base_session_id: str, agent: str | None) -> str:
    if not agent:
        return base_session_id
    suffix = re.sub(r"[^A-Za-z0-9_.-]+", "-", agent).strip("-")
    return f"{base_session_id}-{suffix}" if suffix else base_session_id


def classify_event_with_llm(
    event: dict[str, Any],
    openclaw_bin: str = "openclaw",
    agent: str | None = None,
    model: str | None = None,
    thinking: str = "low",
    session_id: str = "github-agent-bridge-feedback",
    timeout: int = 180,
    prompt_template: str | None = None,
) -> dict[str, Any]:
    cmd = [
        openclaw_bin,
        "agent",
        "--json",
        "--session-id",
        session_id,
        "--timeout",
        str(timeout),
        "--thinking",
        thinking,
        "--message",
        build_learning_prompt(event, prompt_template),
    ]
    if agent:
        cmd.extend(["--agent", agent])
    if model:
        cmd.extend(["--model", model])
    env = os.environ.copy()
    openclaw_dir = os.path.dirname(openclaw_bin)
    if openclaw_dir:
        env["PATH"] = openclaw_dir + os.pathsep + env.get("PATH", "")
    proc = subprocess.run(cmd, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout + 30, env=env)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"openclaw exited {proc.returncode}")
    text = _openclaw_text_from_json(proc.stdout)
    result = _extract_json_object(text)
    return normalize_proposal(event, result)


def normalize_proposal(event: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    is_feedback = bool(result.get("is_feedback"))
    scope = str(result.get("scope") or event["scope"]).strip()
    if not (scope == "global" or scope.startswith("repo:") or scope.startswith("org:")):
        scope = event["scope"]
    rule_type = str(result.get("type") or "domain_context").strip() or "domain_context"
    rule = compact(str(result.get("rule") or ""), 600)
    confidence = float(result.get("confidence") or 0)
    confidence = min(1.0, max(0.0, confidence))
    reason = compact(str(result.get("reason") or ""), 500)
    if not is_feedback:
        rule = ""
        confidence = min(confidence, 0.49)
    return {
        "event_id": event["id"],
        "is_feedback": is_feedback,
        "scope": scope,
        "type": rule_type,
        "rule": rule,
        "confidence": confidence,
        "reason": reason,
    }


def store_proposal(
    db_path: str | Path,
    proposal: dict[str, Any],
    auto_approve_confidence: float,
    model: str = "",
    error: str | None = None,
) -> dict[str, Any]:
    now = utc_now()
    status = "error" if error else "rejected"
    if not error and proposal["is_feedback"] and proposal["rule"] and proposal["confidence"] >= auto_approve_confidence:
        status = "approved"
    elif not error and proposal["is_feedback"] and proposal["rule"]:
        status = "proposed"
    pid = proposal_id(proposal["event_id"], proposal["scope"], proposal["type"], proposal["rule"] or proposal.get("reason", ""))
    with _connect(db_path) as con:
        con.execute(
            """INSERT OR REPLACE INTO feedback_rule_proposals(
                id, event_id, created_at, updated_at, status, scope, type, confidence, rule, reason, model, error
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                pid,
                proposal["event_id"],
                now,
                now,
                status,
                proposal["scope"],
                proposal["type"],
                proposal["confidence"],
                proposal["rule"],
                proposal.get("reason", ""),
                model or "",
                error,
            ),
        )
    if status == "approved":
        add_rule(
            db_path,
            proposal["scope"],
            proposal["type"],
            proposal["rule"],
            proposal["confidence"],
            [proposal["event_id"], pid],
        )
    return next(item for item in list_proposals(db_path, status="", limit=100) if item["id"] == pid)


def approve_proposal(db_path: str | Path, proposal_id: str) -> dict[str, Any] | None:
    now = utc_now()
    with _connect(db_path) as con:
        row = con.execute("SELECT * FROM feedback_rule_proposals WHERE id=?", (proposal_id,)).fetchone()
        if not row:
            return None
        con.execute("UPDATE feedback_rule_proposals SET status='approved', updated_at=?, error=NULL WHERE id=?", (now, proposal_id))
    add_rule(db_path, row["scope"], row["type"], row["rule"], float(row["confidence"]), [row["event_id"], proposal_id])
    return get_proposal(db_path, proposal_id)


def reject_proposal(db_path: str | Path, proposal_id: str) -> dict[str, Any] | None:
    now = utc_now()
    with _connect(db_path) as con:
        row = con.execute("SELECT id FROM feedback_rule_proposals WHERE id=?", (proposal_id,)).fetchone()
        if not row:
            return None
        con.execute("UPDATE feedback_rule_proposals SET status='rejected', updated_at=? WHERE id=?", (now, proposal_id))
    return get_proposal(db_path, proposal_id)


def get_proposal(db_path: str | Path, proposal_id: str) -> dict[str, Any] | None:
    with _connect(db_path) as con:
        row = con.execute("SELECT * FROM feedback_rule_proposals WHERE id=?", (proposal_id,)).fetchone()
        return _proposal_dict(row) if row else None


def delete_rule(db_path: str | Path, rule_id: str) -> bool:
    with _connect(db_path) as con:
        cur = con.execute("DELETE FROM feedback_rules WHERE id=?", (rule_id,))
        return cur.rowcount > 0


def reaction_endpoint(ctx: GitHubContext) -> str | None:
    if not ctx.repo:
        return None
    if ctx.comment_id:
        return f"repos/{ctx.repo}/issues/comments/{ctx.comment_id}/reactions"
    if ctx.review_comment_id:
        return f"repos/{ctx.repo}/pulls/comments/{ctx.review_comment_id}/reactions"
    if ctx.commit_comment_id:
        return f"repos/{ctx.repo}/comments/{ctx.commit_comment_id}/reactions"
    return None


def react_to_feedback_comment(event: dict[str, Any], gh_bin: str = "gh") -> bool:
    ctx = extract_github_context(str(event.get("comment") or ""))
    endpoint = reaction_endpoint(ctx)
    if not endpoint:
        return False
    try:
        result = subprocess.run(
            [
                gh_bin,
                "api",
                "-X",
                "POST",
                endpoint,
                "-f",
                "content=heart",
                "-H",
                "Accept: application/vnd.github+json",
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except OSError:
        return False
    return result.returncode == 0


def learn_from_events(
    db_path: str | Path,
    openclaw_bin: str = "openclaw",
    gh_bin: str = "gh",
    policy: Policy | None = None,
    model: str | None = None,
    thinking: str = "low",
    session_id: str = "github-agent-bridge-feedback",
    limit: int = 10,
    auto_approve_confidence: float = 0.8,
    timeout: int = 180,
    prompt_template: str | None = None,
) -> dict[str, Any]:
    events = pending_events(db_path, limit=limit)
    proposals = []
    reacted = 0
    for event in events:
        try:
            agent = route_agent_for_event(event, policy)
            event_session_id = session_id_for_agent(session_id, agent)
            model_used = model
            try:
                proposal = classify_event_with_llm(
                    event,
                    openclaw_bin=openclaw_bin,
                    agent=agent,
                    model=model,
                    thinking=thinking,
                    session_id=event_session_id,
                    timeout=timeout,
                    prompt_template=prompt_template,
                )
            except Exception as exc:
                if not model or not is_model_override_not_allowed(exc):
                    raise
                model_used = None
                proposal = classify_event_with_llm(
                    event,
                    openclaw_bin=openclaw_bin,
                    agent=agent,
                    model=None,
                    thinking=thinking,
                    session_id=event_session_id,
                    timeout=timeout,
                    prompt_template=prompt_template,
                )
            stored = store_proposal(db_path, proposal, auto_approve_confidence, model=model_used or "")
            proposals.append(stored)
            if stored["status"] == "approved" and react_to_feedback_comment(event, gh_bin=gh_bin):
                reacted += 1
        except Exception as exc:
            fallback = {
                "event_id": event["id"],
                "is_feedback": False,
                "scope": event["scope"],
                "type": "error",
                "rule": "",
                "confidence": 0.0,
                "reason": "classification failed",
            }
            proposals.append(store_proposal(db_path, fallback, auto_approve_confidence, model=model or "", error=str(exc)))
    return {
        "processed": len(events),
        "approved": sum(1 for item in proposals if item["status"] == "approved"),
        "proposed": sum(1 for item in proposals if item["status"] == "proposed"),
        "rejected": sum(1 for item in proposals if item["status"] == "rejected"),
        "errors": sum(1 for item in proposals if item["status"] == "error"),
        "reacted": reacted,
        "proposals": proposals,
    }


def list_proposals(db_path: str | Path, status: str = "", limit: int = 20) -> list[dict[str, Any]]:
    args: list[Any] = []
    sql = "SELECT * FROM feedback_rule_proposals"
    if status:
        sql += " WHERE status=?"
        args.append(status)
    sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
    args.append(limit)
    with _connect(db_path) as con:
        return [_proposal_dict(row) for row in con.execute(sql, args)]


def _proposal_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "event_id": row["event_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "status": row["status"],
        "scope": row["scope"],
        "type": row["type"],
        "confidence": row["confidence"],
        "rule": row["rule"],
        "reason": row["reason"],
        "model": row["model"],
        "error": row["error"],
    }


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
        return [_event_dict(row) for row in con.execute(sql, args)]


def list_repositories(db_path: str | Path) -> list[str]:
    with _connect(db_path) as con:
        rows = con.execute(
            """
            SELECT scope FROM feedback_events
            UNION
            SELECT scope FROM feedback_rules
            UNION
            SELECT scope FROM feedback_rule_proposals
            """
        ).fetchall()
    repos = {
        str(row["scope"]).removeprefix("repo:")
        for row in rows
        if str(row["scope"]).startswith("repo:") and str(row["scope"]).removeprefix("repo:")
    }
    return sorted(repos)


def _event_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
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
