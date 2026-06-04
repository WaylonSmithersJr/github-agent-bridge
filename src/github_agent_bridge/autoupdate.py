from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import __version__
from .models import utc_now
from .queue import JobQueue

CommandRunner = Callable[[Sequence[str], Path | None], subprocess.CompletedProcess[str]]

UPDATE_STATE_KEY = "autoupdate"
ACTIVE_JOB_STATUSES = ("pending", "running", "waiting_approval")
RISKY_PATH_PREFIXES = (
    "src/github_agent_bridge/cli.py",
    "src/github_agent_bridge/dispatch.py",
    "src/github_agent_bridge/executor.py",
    "src/github_agent_bridge/monitor.py",
    "src/github_agent_bridge/parser.py",
    "src/github_agent_bridge/policy.py",
    "src/github_agent_bridge/queue.py",
    "src/github_agent_bridge/reader.py",
    "src/github_agent_bridge/reader_run.py",
    "src/github_agent_bridge/sql/",
)
DASHBOARD_PATH_PREFIXES = (
    "dashboard/",
    "src/github_agent_bridge/backend.py",
    "src/github_agent_bridge/dashboard_data.py",
    "src/github_agent_bridge/dashboard_static/",
)


@dataclass(frozen=True)
class ReleaseInfo:
    tag_name: str
    name: str = ""
    url: str = ""
    body: str = ""
    published_at: str = ""
    source: str = "github_release"

    def to_json(self) -> dict[str, str]:
        return {
            "tag_name": self.tag_name,
            "name": self.name,
            "url": self.url,
            "body": self.body,
            "published_at": self.published_at,
            "source": self.source,
        }


def _default_runner(args: Sequence[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(args), cwd=cwd, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def _run_json(args: Sequence[str], cwd: Path | None, runner: CommandRunner) -> dict[str, Any]:
    proc = runner(args, cwd)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"{args[0]} failed with exit code {proc.returncode}")
    try:
        return json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{args[0]} returned invalid JSON") from exc


def latest_release(repo: str, *, gh_bin: str = "gh", runner: CommandRunner = _default_runner) -> ReleaseInfo:
    data = _run_json(
        [
            gh_bin,
            "release",
            "view",
            "--repo",
            repo,
            "--json",
            "tagName,name,url,body,publishedAt,isDraft,isPrerelease",
        ],
        None,
        runner,
    )
    tag_name = str(data.get("tagName") or "")
    if not tag_name:
        raise RuntimeError("latest release did not include a tagName")
    return ReleaseInfo(
        tag_name=tag_name,
        name=str(data.get("name") or ""),
        url=str(data.get("url") or ""),
        body=str(data.get("body") or ""),
        published_at=str(data.get("publishedAt") or ""),
    )


def _git_output(args: Sequence[str], repo_dir: Path, runner: CommandRunner) -> str:
    proc = runner(["git", *args], repo_dir)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "git failed")
    return proc.stdout.strip()


def changed_files_between(repo_dir: Path, base_ref: str, target_ref: str, *, runner: CommandRunner = _default_runner) -> list[str]:
    output = _git_output(["diff", "--name-only", f"{base_ref}..{target_ref}"], repo_dir, runner)
    return [line.strip() for line in output.splitlines() if line.strip()]


def classify_changed_files(files: Sequence[str]) -> dict[str, Any]:
    risky_files = [path for path in files if path.startswith(RISKY_PATH_PREFIXES)]
    migration_files = [path for path in files if path.startswith("src/github_agent_bridge/sql/") or "/migrations/" in path]
    dashboard_files = [path for path in files if path.startswith(DASHBOARD_PATH_PREFIXES)]
    dashboard_only = bool(files) and len(dashboard_files) == len(files)
    risk = "dashboard_only" if dashboard_only else "executor_or_shared"
    if migration_files:
        risk = "migration_required"
    elif risky_files:
        risk = "executor_or_queue"
    elif not files:
        risk = "none"
    return {
        "risk": risk,
        "dashboard_only": dashboard_only,
        "risky_files": risky_files,
        "migration_files": migration_files,
        "changed_files": list(files),
    }


def active_queue_counts(queue: JobQueue) -> dict[str, int]:
    stats = queue.stats()
    return {status: int(stats.get(status, 0)) for status in ACTIVE_JOB_STATUSES}


def load_update_state(queue: JobQueue) -> dict[str, Any]:
    raw = queue.get_state(UPDATE_STATE_KEY, "")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"state_error": "invalid_autoupdate_state"}
    return data if isinstance(data, dict) else {}


def save_update_state(queue: JobQueue, state: dict[str, Any]) -> None:
    queue.set_state(UPDATE_STATE_KEY, json.dumps(state, sort_keys=True))


def plan_update(
    db: str | Path,
    *,
    repo: str = "pilipilisbot/github-agent-bridge",
    repo_dir: str | Path = ".",
    target_tag: str | None = None,
    gh_bin: str = "gh",
    installed_version: str = __version__,
    runner: CommandRunner = _default_runner,
) -> dict[str, Any]:
    queue = JobQueue(db)
    repo_path = Path(repo_dir).expanduser().resolve()
    current_tag = f"v{installed_version.lstrip('v')}"
    release = ReleaseInfo(tag_name=target_tag, source="explicit_target") if target_tag else latest_release(repo, gh_bin=gh_bin, runner=runner)
    active_counts = active_queue_counts(queue)
    active_total = sum(active_counts.values())

    warnings: list[str] = []
    try:
        files = [] if release.tag_name == current_tag else changed_files_between(repo_path, current_tag, release.tag_name, runner=runner)
    except RuntimeError as exc:
        files = []
        warnings.append(f"changed_files_unavailable: {exc}")
    classification = classify_changed_files(files)
    up_to_date = release.tag_name == current_tag
    migration_required = bool(classification["migration_files"])
    executor_reload_pending = False
    dashboard_restart_allowed = False
    executor_restart_allowed = False
    blocked_reason = ""

    if up_to_date:
        decision = "noop"
    elif migration_required and active_total:
        decision = "defer_migration"
        blocked_reason = "active_jobs_block_migration"
    elif classification["dashboard_only"]:
        decision = "stage_dashboard_reload"
        dashboard_restart_allowed = True
    elif active_total:
        decision = "stage_defer_executor_reload"
        executor_reload_pending = True
        dashboard_restart_allowed = True
        blocked_reason = "active_jobs_block_executor_reload"
    else:
        decision = "stage_full_reload"
        dashboard_restart_allowed = True
        executor_restart_allowed = True

    return {
        "checked_at": utc_now(),
        "installed_version": installed_version,
        "installed_tag": current_tag,
        "target": release.to_json(),
        "up_to_date": up_to_date,
        "queue": {
            "active_counts": active_counts,
            "active_total": active_total,
        },
        "classification": classification,
        "decision": decision,
        "dashboard_restart_allowed": dashboard_restart_allowed,
        "executor_restart_allowed": executor_restart_allowed,
        "executor_reload_pending": executor_reload_pending,
        "blocked_reason": blocked_reason,
        "warnings": warnings,
    }


def record_update_plan(db: str | Path, plan: dict[str, Any]) -> dict[str, Any]:
    queue = JobQueue(db)
    state = {
        "updated_at": utc_now(),
        "installed_version": plan["installed_version"],
        "installed_tag": plan["installed_tag"],
        "target": plan["target"],
        "decision": plan["decision"],
        "executor_reload_pending": bool(plan["executor_reload_pending"]),
        "blocked_reason": plan["blocked_reason"],
        "queue": plan["queue"],
        "classification": {
            "risk": plan["classification"]["risk"],
            "migration_files": plan["classification"]["migration_files"],
            "risky_files": plan["classification"]["risky_files"],
        },
        "warnings": plan["warnings"],
    }
    save_update_state(queue, state)
    return state
