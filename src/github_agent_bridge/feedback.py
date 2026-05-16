from __future__ import annotations

import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

from .models import GitHubContext, Notification


ACTIONABLE_FEEDBACK_ACTIONS = {"reply_comment", "open_issue", "submit_review", "docs_update", "content_change"}
FEEDBACK_DECISIONS = {"auto_trusted", "ask"}
DEFAULT_LEARNER_BIN = "github-agent-feedback-learner"


def enabled() -> bool:
    return os.environ.get("GITHUB_AGENT_BRIDGE_FEEDBACK_LEARNING", "1") != "0"


def learner_path() -> Path | None:
    configured = os.environ.get("GITHUB_AGENT_BRIDGE_FEEDBACK_LEARNER")
    if configured:
        return Path(configured)
    discovered = shutil.which(DEFAULT_LEARNER_BIN)
    return Path(discovered) if discovered else None


def compact(text: str, limit: int = 1600) -> str:
    clean = re.sub(r"\s+", " ", text or "").strip()
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rstrip() + "..."


def event_id(n: Notification) -> str:
    seed = n.message_id or f"{n.uid}:{n.subject}:{n.received_at}"
    return "github-agent-bridge-" + uuid.uuid5(uuid.NAMESPACE_URL, seed).hex[:16]


def capture_feedback(n: Notification, ctx: GitHubContext, action: str, decision: str, work_intent: str) -> bool:
    """Send a GitHub notification to the local feedback learner when relevant.

    The learner is responsible for deciding whether the event becomes a
    synthesized rule or remains raw-only. This hook is intentionally best-effort:
    feedback capture must never block queueing GitHub work.
    """
    if not enabled() or decision not in FEEDBACK_DECISIONS or action not in ACTIONABLE_FEEDBACK_ACTIONS:
        return False

    path = learner_path()
    if path is None:
        return False
    if path.is_absolute() and not path.exists():
        return False

    repo = ctx.repo or "unknown/repo"
    scope = f"repo:{repo}" if repo != "unknown/repo" else "github"
    context = f"GitHub bridge {action}/{decision}; work_intent={work_intent}; thread={ctx.work_key}"
    comment = compact(f"{n.subject}\n\n{n.body}")

    try:
        result = subprocess.run(
            [
                str(path),
                "ingest",
                "--source",
                "github-agent-bridge",
                "--scope",
                scope,
                "--actor",
                "github",
                "--event-id",
                event_id(n),
                "--occurred-at",
                n.received_at,
                "--comment",
                comment,
                "--context",
                context,
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return False
    return result.returncode == 0
