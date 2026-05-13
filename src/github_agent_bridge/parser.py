from __future__ import annotations

import re
from email.message import Message
from email.header import decode_header

from .models import GitHubContext

REVIEW_ONLY_PATTERNS = ("fes-ne una review", "fes una review", "fes review", "fer una review", "fes-ne una revisio", "fes-ne una revisió", "fes una revisio", "fes una revisió", "fer una revisio", "fer una revisió", "review de la pr", "revisió de la pr", "revisio de la pr", "revisa aquesta pr", "revisa els canvis", "revisar els canvis", "com veus els canvis", "què et semblen els canvis", "que et semblen els canvis", "what do you think of these changes", "please review", "can you review")
IMPLEMENTATION_PATTERNS = ("fes els canvis", "fes-ho", "implementa", "modifica", "canvia", "arregla", "corregeix", "fix", "push", "commit", "aplica", "resol", "resolve")
BOT_MENTION_PATTERNS = ("@pilipilisbot", "pilipilisbot", "you are receiving this because you were mentioned")
ASSIGNMENT_PATTERNS = ("assigned you", "assigned to you", "you were assigned", "you are assigned", "assigned pilipilisbot", "assigned @pilipilisbot")
REVIEW_REQUEST_PATTERNS = ("requested your review", "requested a review from you", "you were requested for review", "review requested", "requested review from pilipilisbot", "requested review from @pilipilisbot", "requested @pilipilisbot")
COPILOT_REVIEW_PATTERNS = ("copilot-pull-request-reviewer", "github-copilot", "github copilot", "copilot reviewed", "copilot commented", "copilot left a comment", "copilot suggested", "copilot requested changes")


def decode_header_value(value: str | None) -> str:
    if not value:
        return ""
    out = ""
    for part, enc in decode_header(value):
        out += part.decode(enc or "utf-8", errors="replace") if isinstance(part, bytes) else part
    return out.strip()


def extract_body_text(msg: Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                return (part.get_payload(decode=True) or b"").decode(part.get_content_charset() or "utf-8", "replace")
    return (msg.get_payload(decode=True) or b"").decode(msg.get_content_charset() or "utf-8", "replace")


def parse_auth_results(msg: Message) -> dict[str, bool]:
    raw = "\n".join(msg.get_all("Authentication-Results", []))
    return {"spf": "spf=pass" in raw, "dkim": "dkim=pass" in raw, "dmarc": "dmarc=pass" in raw}


def _contains_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(p in text for p in patterns)


def github_event_flags(subject: str, body: str) -> dict[str, bool]:
    text = f"{subject}\n{body}".lower()
    return {"bot_mentioned": _contains_any(text, BOT_MENTION_PATTERNS), "assigned": _contains_any(text, ASSIGNMENT_PATTERNS), "review_requested": _contains_any(text, REVIEW_REQUEST_PATTERNS), "copilot_review": _contains_any(text, COPILOT_REVIEW_PATTERNS)}


def classify_work_intent(subject: str, body: str) -> str:
    text = f"{subject}\n{body}".lower()
    flags = github_event_flags(subject, body)
    asks_review = flags["review_requested"] or _contains_any(text, REVIEW_ONLY_PATTERNS)
    asks_implementation = _contains_any(text, IMPLEMENTATION_PATTERNS)
    return "review_only" if asks_review and not asks_implementation else "work_allowed"


def classify_github_action(subject: str, body: str) -> str:
    text = f"{subject}\n{body}".lower()
    flags = github_event_flags(subject, body)
    if "merged" in text:
        return "sync_after_merge"
    # PR reviews/comments should be handled as replies even when GitHub's footer
    # also says the bot was assigned to the thread.
    if flags["review_requested"]:
        return "submit_review"
    if flags["copilot_review"] or "pullrequestreview" in text:
        return "reply_comment"
    if flags["assigned"]:
        return "open_issue"
    if flags["bot_mentioned"]:
        return "reply_comment"
    return "archive_notification"


def extract_github_context(body: str) -> GitHubContext:
    urls = re.findall(r"https://github\.com/[^\s>]+", body)
    repo = None; issue_number = None; comment_id = None; review_id = None; review_comment_id = None; target_kind = None
    for url in urls:
        m = re.search(r"github\.com/([^/]+/[^/]+)/(issues|pull)/(\d+)", url)
        if not m:
            continue
        repo = m.group(1).lower(); issue_number = int(m.group(3))
        cm = re.search(r"issuecomment-(\d+)", url); rv = re.search(r"pullrequestreview-(\d+)", url); rc = re.search(r"discussion_r(\d+)", url)
        if cm:
            comment_id = int(cm.group(1)); target_kind = "issue_comment"; break
        if rc:
            review_comment_id = int(rc.group(1)); target_kind = "review_comment"; break
        if rv:
            review_id = int(rv.group(1)); target_kind = "review"; continue
        if target_kind is None:
            target_kind = "issue"
    return GitHubContext(urls, repo, issue_number, comment_id, review_id, review_comment_id, target_kind)
