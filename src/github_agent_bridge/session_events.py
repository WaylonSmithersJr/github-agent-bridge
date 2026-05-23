from __future__ import annotations

import re

MAX_EVENT_DETAIL_CHARS = 2000
SECRET_PATTERNS = [
    re.compile(r"(?i)(token|secret|password|authorization|cookie)=\S+"),
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
]


def redact_event_detail(value: str | None, *, max_chars: int = MAX_EVENT_DETAIL_CHARS) -> str | None:
    if not value:
        return None
    text = value.replace("\x00", "")
    for pattern in SECRET_PATTERNS:
        text = pattern.sub(lambda match: match.group(0).split("=", 1)[0] + "=[redacted]" if "=" in match.group(0) else "[redacted]", text)
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}... [truncated]"
