from __future__ import annotations

import re
from typing import Any


SESSION_ID_PREFIX = "github-agent-bridge-job"
SESSION_ID_PATTERN = re.compile(r"[^A-Za-z0-9_.:-]+")


def session_id_for_job(job_id: int) -> str:
    return f"{SESSION_ID_PREFIX}-{job_id}"


def normalize_session_id(value: str) -> str:
    normalized = SESSION_ID_PATTERN.sub("-", value.strip())
    normalized = normalized.strip("-")
    return normalized or SESSION_ID_PREFIX


def job_session_metadata(job: dict[str, Any]) -> dict[str, Any]:
    metadata = job.get("metadata") if isinstance(job.get("metadata"), dict) else {}
    session_id = metadata.get("openclaw_session_id") or session_id_for_job(int(job["id"]))
    return {
        "id": normalize_session_id(str(session_id)),
        "source": "metadata" if metadata.get("openclaw_session_id") else "derived",
        "transcript_available": False,
        "transcript_exposure": "redacted_dashboard",
    }
