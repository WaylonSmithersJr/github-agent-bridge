import sqlite3

from github_agent_bridge.models import Notification
from github_agent_bridge import monitor as monitor_module
from github_agent_bridge.monitor import MonitorThresholds, monitor
from github_agent_bridge.policy import Policy
from github_agent_bridge.queue import JobQueue


def notif(uid=1, mid="<1@github.com>", body="@pilipilisbot https://github.com/gisce/erp/pull/1#issuecomment-10"):
    return Notification(uid=uid, message_id=mid, subject="Re: [gisce/erp] PR", from_addr="GitHub <notifications@github.com>", body=body, auth={"spf": True, "dkim": True, "dmarc": True})


def test_monitor_ok_on_empty_initialized_db(tmp_path):
    db = tmp_path / "bridge.sqlite3"
    JobQueue(db)
    report = monitor(db, check_systemd=False)
    assert report.ok is True
    assert "pending=0" in report.text()


def test_monitor_alerts_on_blocked_job(tmp_path):
    db = tmp_path / "bridge.sqlite3"
    q = JobQueue(db)
    job, _ = q.enqueue(notif(), Policy(trusted_orgs={"gisce"}))
    q.finish(job.id, "blocked", "boom", "details")
    report = monitor(db, check_systemd=False)
    assert report.ok is False
    assert any("blocked jobs: 1" in a for a in report.alerts)


def test_monitor_alerts_on_old_pending_job(tmp_path):
    db = tmp_path / "bridge.sqlite3"
    q = JobQueue(db)
    q.enqueue(notif(), Policy(trusted_orgs={"gisce"}))
    con = sqlite3.connect(db)
    con.execute("UPDATE jobs SET created_at='2000-01-01T00:00:00Z', updated_at='2000-01-01T00:00:00Z'")
    con.commit()
    report = monitor(db, thresholds=MonitorThresholds(pending_warn_seconds=1), check_systemd=False)
    assert report.ok is False
    assert any("pending queue oldest age" in a for a in report.alerts)


def test_monitor_alerts_on_old_running_job(tmp_path):
    db = tmp_path / "bridge.sqlite3"
    q = JobQueue(db)
    q.enqueue(notif(), Policy(trusted_orgs={"gisce"}))
    job = q.claim_next("worker-1")
    assert job is not None
    con = sqlite3.connect(db)
    con.execute("UPDATE jobs SET started_at='2000-01-01T00:00:00Z', updated_at='2000-01-01T00:00:00Z' WHERE id=?", (job.id,))
    con.commit()
    report = monitor(db, thresholds=MonitorThresholds(work_running_warn_seconds=1), check_systemd=False)
    assert report.ok is False
    assert any("running job" in a for a in report.alerts)
    assert "running detail: job=" in report.text()


def test_monitor_alerts_when_running_job_has_no_executor_child(tmp_path, monkeypatch):
    db = tmp_path / "bridge.sqlite3"
    q = JobQueue(db)
    q.enqueue(notif(), Policy(trusted_orgs={"gisce"}))
    q.claim_next("worker-1")
    monkeypatch.setattr(monitor_module, "_is_active", lambda unit: "active")
    monkeypatch.setattr(monitor_module, "_main_pid", lambda unit: 123)
    monkeypatch.setattr(monitor_module, "_direct_children", lambda pid: [])
    monkeypatch.setattr(monitor_module, "_last_service_result", lambda unit: ("success", "0", 42))

    report = monitor(db)

    assert report.ok is False
    assert any("running jobs exist but executor has no child process" in a for a in report.alerts)


def test_monitor_reports_executor_child_processes(tmp_path, monkeypatch):
    db = tmp_path / "bridge.sqlite3"
    q = JobQueue(db)
    q.enqueue(notif(), Policy(trusted_orgs={"gisce"}))
    q.claim_next("worker-1")
    monkeypatch.setattr(monitor_module, "_is_active", lambda unit: "active")
    monkeypatch.setattr(monitor_module, "_main_pid", lambda unit: 123)
    monkeypatch.setattr(monitor_module, "_direct_children", lambda pid: [{"pid": 456, "cmd": "openclaw agent"}])
    monkeypatch.setattr(monitor_module, "_last_service_result", lambda unit: ("success", "0", 42))

    report = monitor(db)

    assert report.metrics["executor_pid"] == 123
    assert report.metrics["executor_children"] == [{"pid": 456, "cmd": "openclaw agent"}]
    assert "executor children: 456:openclaw agent" in report.text()


def test_monitor_reports_recent_reader_from_systemd_age(tmp_path, monkeypatch):
    db = tmp_path / "bridge.sqlite3"
    JobQueue(db)
    monkeypatch.setattr(monitor_module, "_is_active", lambda unit: "active")
    monkeypatch.setattr(monitor_module, "_last_service_result", lambda unit: ("success", "0", 42))

    report = monitor(db, thresholds=MonitorThresholds(reader_recent_seconds=180))

    assert report.ok is True
    assert report.metrics["reader_recent"] is True
    assert report.metrics["reader_last_age_seconds"] == 42
    assert "reader_recent=True" in report.text()


def test_monitor_alerts_on_stale_reader_from_systemd_age(tmp_path, monkeypatch):
    db = tmp_path / "bridge.sqlite3"
    JobQueue(db)
    monkeypatch.setattr(monitor_module, "_is_active", lambda unit: "active")
    monkeypatch.setattr(monitor_module, "_last_service_result", lambda unit: ("success", "0", 181))

    report = monitor(db, thresholds=MonitorThresholds(reader_recent_seconds=180))

    assert report.ok is False
    assert report.metrics["reader_recent"] is False
    assert any("reader last run age 181s > 180s" in a for a in report.alerts)
