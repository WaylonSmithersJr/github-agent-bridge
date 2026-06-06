from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass

from .models import Notification


@dataclass(frozen=True)
class GitHubNotificationResult:
    notification: Notification
    thread_id: str
    html_url: str | None


def run_gh_json(args: list[str], gh_bin: str = "gh") -> object:
    proc = subprocess.run([gh_bin, *args], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"gh failed ({proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}")
    return json.loads(proc.stdout or "null")


def _api_get(url: str, gh_bin: str) -> dict:
    data = run_gh_json(["api", url], gh_bin)
    return data if isinstance(data, dict) else {}


def _thread_number_from_html_url(url: str | None) -> int | None:
    if not url:
        return None
    parts = url.split("/")
    for marker in ("issues", "pull"):
        if marker in parts:
            idx = parts.index(marker)
            if idx + 1 < len(parts):
                try:
                    return int(parts[idx + 1].split("#", 1)[0])
                except ValueError:
                    return None
    return None


def _issue_kind(issue: dict, subject_type: str | None) -> str:
    if "pull_request" in issue or (subject_type or "").lower() == "pullrequest":
        return "PR"
    return "Issue"


def notification_from_github_thread(thread: dict, gh_bin: str = "gh") -> GitHubNotificationResult | None:
    """Convert one GitHub notifications API thread to the existing email-shaped Notification.

    The rest of the bridge already understands GitHub notification emails. This
    adapter deliberately creates the same shape: trusted GitHub sender, a
    github.com message id, and a body containing the canonical GitHub URL.
    """
    thread_id = str(thread.get("id") or "")
    subject = thread.get("subject") if isinstance(thread.get("subject"), dict) else {}
    repo = thread.get("repository") if isinstance(thread.get("repository"), dict) else {}
    repo_name = str(repo.get("full_name") or "").lower()
    if not thread_id or not repo_name or not subject:
        return None

    latest_comment_url = subject.get("latest_comment_url")
    subject_url = subject.get("url")
    subject_type = subject.get("type")
    title = subject.get("title") or "GitHub notification"

    payload = _api_get(str(latest_comment_url or subject_url), gh_bin) if (latest_comment_url or subject_url) else {}
    html_url = payload.get("html_url")
    body = payload.get("body") or ""
    user = payload.get("user") if isinstance(payload.get("user"), dict) else {}

    issue_number = _thread_number_from_html_url(html_url)
    issue = {}
    if issue_number is not None:
        issue = _api_get(f"repos/{repo_name}/issues/{issue_number}", gh_bin)
        if not body:
            body = issue.get("body") or ""
        title = issue.get("title") or title
        html_url = html_url or issue.get("html_url")
        if not user:
            user = issue.get("user") if isinstance(issue.get("user"), dict) else {}

    kind = _issue_kind(issue, str(subject_type or ""))
    thread_label = f"{kind} #{issue_number}" if issue_number is not None else str(subject_type or "Thread")
    body_parts = [
        body,
        "",
        str(html_url or ""),
        "",
        f"GitHub notification reason: {thread.get('reason') or 'unknown'}",
        f"GitHub notification type: {subject_type or 'unknown'}",
    ]
    login = user.get("login") or "GitHub"
    avatar = user.get("avatar_url") or ""
    if login != "GitHub":
        body_parts.append(f"GitHub actor: @{login}")
    if avatar:
        body_parts.append(f"GitHub actor avatar: {avatar}")

    notification = Notification(
        uid=int(thread_id) if thread_id.isdigit() else None,
        message_id=f"<github-notification/{thread_id}/{thread.get('updated_at') or ''}@github.com>",
        subject=f"Re: [{repo_name}] {title} ({thread_label})",
        from_addr=f"{login} <notifications@github.com>",
        body="\n".join(body_parts),
        received_at=thread.get("updated_at") or thread.get("last_read_at") or "",
        auth={"spf": True, "dkim": True, "dmarc": True},
    )
    return GitHubNotificationResult(notification=notification, thread_id=thread_id, html_url=html_url)


def list_notification_threads(gh_bin: str = "gh", *, all_threads: bool = False, participating: bool = False) -> list[dict]:
    args = ["api", "-X", "GET", "notifications", "--paginate", "-f", "per_page=100"]
    if all_threads:
        args.extend(["-f", "all=true"])
    if participating:
        args.extend(["-f", "participating=true"])
    data = run_gh_json(args, gh_bin)
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def mark_thread_read(thread_id: str, gh_bin: str = "gh") -> None:
    run_gh_json(["api", "-X", "PATCH", f"notifications/threads/{thread_id}"], gh_bin)
