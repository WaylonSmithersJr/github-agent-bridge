from __future__ import annotations

from pathlib import Path

from github_agent_bridge import monitor_alert


def make_config(tmp_path: Path) -> monitor_alert.AlertConfig:
    return monitor_alert.AlertConfig(
        bridge_bin="/tmp/github-agent-bridge",
        openclaw_bin="/tmp/openclaw",
        db="/tmp/bridge.sqlite3",
        policy="/tmp/policy.json",
        channel="telegram",
        target="43532269",
        state_dir=tmp_path,
        resend_seconds=900,
        auto_unlock_seconds=900,
        pending_warn_seconds=300,
        review_running_warn_seconds=600,
        work_running_warn_seconds=900,
    )


def test_should_send_alert_persists_and_throttles(tmp_path):
    state_file = tmp_path / "monitor-alert.state"

    assert monitor_alert.should_send_alert(state_file, "boom", resend_seconds=900, now=1000) is True
    assert monitor_alert.should_send_alert(state_file, "boom", resend_seconds=900, now=1500) is False
    assert monitor_alert.should_send_alert(state_file, "boom", resend_seconds=900, now=2001) is True


def test_load_state_accepts_legacy_shell_format(tmp_path):
    state_file = tmp_path / "monitor-alert.state"
    state_file.write_text("LAST_HASH='abc'\nLAST_TS=123\n", encoding="utf-8")

    assert monitor_alert.load_state(state_file) == ("abc", 123)


def test_maybe_unlock_stale_runs_when_executor_has_no_children(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    monkeypatch.setattr(monitor_alert, "get_main_pid", lambda unit="github-agent-bridge.service": "123")
    monkeypatch.setattr(monitor_alert, "has_child_processes", lambda pid: False)
    monkeypatch.setattr(
        monitor_alert,
        "_run",
        lambda args, check=False: type("Proc", (), {"stdout": '{"unlocked":1}\n'})(),
    )

    output = monitor_alert.maybe_unlock_stale(config, "running job 7 owner/repo#1 age 1200s > 900s")

    assert output == '{"unlocked":1}\n'


def test_maybe_unlock_stale_skips_without_running_job_message(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    called = False

    def fail(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("unlock should not run")

    monkeypatch.setattr(monitor_alert, "_run", fail)

    output = monitor_alert.maybe_unlock_stale(config, "pending queue oldest age 999s > 300s")

    assert output == ""
    assert called is False
