from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, UTC
import json
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class GitHubContext:
    urls: list[str]
    repo: str | None = None
    issue_number: int | None = None
    comment_id: int | None = None
    review_id: int | None = None
    review_comment_id: int | None = None
    target_kind: str | None = None

    @property
    def work_key(self) -> str:
        if self.repo and self.issue_number:
            return f"{self.repo}#{self.issue_number}"
        return "unknown/repo#0"

    @property
    def short_url(self) -> str:
        return self.urls[0] if self.urls else "(sense URL)"

    def to_json(self) -> str:
        return json.dumps(self.__dict__, ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_json(cls, value: str) -> "GitHubContext":
        return cls(**json.loads(value))


@dataclass(frozen=True)
class Notification:
    uid: int | None
    message_id: str
    subject: str
    from_addr: str
    body: str
    received_at: str = field(default_factory=utc_now)
    auth: dict[str, bool] = field(default_factory=dict)


@dataclass(frozen=True)
class Job:
    id: int
    work_key: str
    repo: str | None
    thread: int | None
    status: str
    action: str
    work_intent: str
    subject: str
    message_id: str
    uid: int | None
    context: GitHubContext
    attempts: int = 0
    coalesced_count: int = 0
    last_error: str | None = None
    locked_by: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
