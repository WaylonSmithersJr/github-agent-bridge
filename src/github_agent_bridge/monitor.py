from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .dashboard_data import inspect_db_read_only
from .process_inspection import direct_children


@dataclass(frozen=True)
class MonitorThresholds:
    pending_warn_seconds: int = 300
    review_running_warn_seconds: int = 1200
    work_running_warn_seconds: int = 4200
    reader_recent_seconds: int = 180


@dataclass
class MonitorReport:
    ok: bool
    alerts: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "alerts": self.alerts, "metrics": self.metrics}

    def text(self) -> str:
        status = "OK" if self.ok else "ALERT"
        parts = [f"{status} github-agent-bridge"]
        metrics = self.metrics
        compact = [
            f"executor={metrics.get('executor_service', 'unknown')}",
            f"reader_timer={metrics.get('reader_timer', 'unknown')}",
            f"reader_recent={metrics.get('reader_recent', 'unknown')}",
            f"pending={metrics.get('pending', 0)}",
            f"blocked={metrics.get('blocked', 0)}",
            f"running={metrics.get('running', 0)}",
            f"oldest_pending={metrics.get('oldest_pending_age_seconds') if metrics.get('oldest_pending_age_seconds') is not None else '-'}",
            f"last_uid={metrics.get('last_uid', '-')}",
        ]
        parts.append(" ".join(compact))
        if self.alerts:
            parts.extend(f"- {a}" for a in self.alerts)
        for job in metrics.get("running_jobs", []):
            last = job.get("last_worklog") or {}
            parts.append(
                "- running detail: "
                f"job={job.get('id')} key={job.get('work_key')} "
                f"intent={job.get('work_intent')} attempts={job.get('attempts')} "
                f"worker={job.get('locked_by')} age={job.get('age_seconds')}s "
                f"idle={job.get('idle_seconds')}s "
                f"last={last.get('phase', '-')}/{last.get('summary', '-')}"
            )
        children = metrics.get("executor_children") or []
        if children:
            child_text = ", ".join(f"{child.get('pid')}:{child.get('cmd') or '-'}" for child in children[:5])
            parts.append(f"- executor children: {child_text}")
        return "\n".join(parts)


def _run_systemctl(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["systemctl", "--user", *args], check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def _is_active(unit: str) -> str:
    proc = _run_systemctl(["is-active", unit])
    return proc.stdout.strip() or "unknown"


def _last_service_result(unit: str) -> tuple[str, str | None, int | None]:
    proc = _run_systemctl([
        "show",
        unit,
        "--property=Result,ExecMainStatus,InactiveEnterTimestampMonotonic,ActiveEnterTimestampMonotonic",
    ])
    props: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        props[key] = value.strip()

    result = props.get("Result") or "unknown"
    exit_status = props.get("ExecMainStatus") or None
    finished_raw = props.get("InactiveEnterTimestampMonotonic") or props.get("ActiveEnterTimestampMonotonic")
    age_seconds: int | None = None
    try:
        finished_us = int(finished_raw or "0")
    except ValueError:
        finished_us = 0
    if finished_us > 0:
        now_us = time.monotonic_ns() // 1000
        age_seconds = max(0, int((now_us - finished_us) / 1_000_000))
    return result, exit_status, age_seconds


def _main_pid(unit: str) -> int | None:
    proc = _run_systemctl(["show", unit, "--property=MainPID", "--value"])
    value = (proc.stdout or "").strip()
    try:
        pid = int(value)
    except ValueError:
        return None
    return pid or None


def _direct_children(pid: int) -> list[dict[str, Any]]:
    return direct_children(pid)


def inspect_db(path: str | Path) -> dict[str, Any]:
    return inspect_db_read_only(path)


def monitor(
    db: str | Path,
    executor_unit: str = "github-agent-bridge.service",
    reader_timer_unit: str = "github-agent-bridge-reader.timer",
    reader_service_unit: str = "github-agent-bridge-reader.service",
    thresholds: MonitorThresholds | None = None,
    check_systemd: bool = True,
) -> MonitorReport:
    thresholds = thresholds or MonitorThresholds()
    metrics = inspect_db(db)
    alerts: list[str] = []

    if not metrics.get("db_exists"):
        alerts.append(f"database missing: {metrics.get('db_path')}")
    elif not metrics.get("schema_ok", True):
        alerts.append("database schema missing jobs table")

    pending = int(metrics.get("pending", 0) or 0)
    blocked = int(metrics.get("blocked", 0) or 0)
    waiting = int(metrics.get("waiting_approval", 0) or 0)
    pending_age = metrics.get("oldest_pending_age_seconds")
    if blocked:
        alerts.append(f"blocked jobs: {blocked}")
    if pending and pending_age is not None and pending_age > thresholds.pending_warn_seconds:
        alerts.append(f"pending queue oldest age {pending_age}s > {thresholds.pending_warn_seconds}s")
    if waiting:
        metrics["waiting_approval"] = waiting

    for job in metrics.get("running_jobs", []):
        age = job.get("age_seconds")
        if age is None:
            continue
        limit = thresholds.review_running_warn_seconds if job.get("work_intent") == "review_only" else thresholds.work_running_warn_seconds
        if age > limit:
            alerts.append(f"running job {job.get('id')} {job.get('work_key')} age {age}s > {limit}s")

    if check_systemd:
        executor_state = _is_active(executor_unit)
        executor_pid = _main_pid(executor_unit)
        children = _direct_children(executor_pid) if executor_pid else []
        timer_state = _is_active(reader_timer_unit)
        reader_result, reader_exit, reader_age = _last_service_result(reader_service_unit)
        metrics.update({
            "executor_service": executor_state,
            "executor_pid": executor_pid,
            "executor_children": children,
            "reader_timer": timer_state,
            "reader_last_result": reader_result,
            "reader_last_exit_status": reader_exit,
            "reader_last_age_seconds": reader_age,
        })
        if executor_state != "active":
            alerts.append(f"executor service is {executor_state}")
        if metrics.get("running_jobs") and executor_state == "active" and not children:
            alerts.append("running jobs exist but executor has no child process")
        if timer_state != "active":
            alerts.append(f"reader timer is {timer_state}")
        if reader_result not in ("success", "unknown"):
            alerts.append(f"reader last result is {reader_result} exit={reader_exit}")
        if reader_age is None:
            metrics["reader_recent"] = "unknown"
        else:
            reader_recent = reader_age <= thresholds.reader_recent_seconds
            metrics["reader_recent"] = reader_recent
            if not reader_recent:
                alerts.append(f"reader last run age {reader_age}s > {thresholds.reader_recent_seconds}s")

    return MonitorReport(ok=not alerts, alerts=alerts, metrics=metrics)


def report_json(report: MonitorReport) -> str:
    return json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
