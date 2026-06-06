from __future__ import annotations

import subprocess

from github_agent_bridge import systemd_status as systemd_module


def test_systemd_status_parses_bridge_unit_state(monkeypatch):
    def fake_run(args, **kwargs):
        assert args[:3] == ["systemctl", "--user", "show"]
        assert kwargs["check"] is False
        return subprocess.CompletedProcess(
            args,
            0,
            stdout="\n".join(
                [
                    "Id=github-agent-bridge.service",
                    "LoadState=loaded",
                    "ActiveState=active",
                    "SubState=running",
                    "Result=success",
                    "ExecMainStatus=0",
                    "MainPID=123",
                    "ActiveEnterTimestamp=Sat 2026-06-06 09:00:00 UTC",
                    "ActiveEnterTimestampMonotonic=1000000",
                    "NextElapseUSecRealtime=",
                    "LastTriggerUSec=",
                    "UnitFileState=enabled",
                ]
            ),
            stderr="",
        )

    monkeypatch.setenv("GITHUB_AGENT_BRIDGE_EXECUTOR_UNIT", "github-agent-bridge.service")
    monkeypatch.setattr(systemd_module, "BRIDGE_UNITS", [systemd_module.BridgeUnit("executor", "service", "GITHUB_AGENT_BRIDGE_EXECUTOR_UNIT", "github-agent-bridge.service")])
    monkeypatch.setattr(systemd_module.subprocess, "run", fake_run)
    monkeypatch.setattr(systemd_module.time, "monotonic", lambda: 91.0)

    status = systemd_module.systemd_status()

    assert status["available"] is True
    assert status["errors"] == []
    assert status["units"] == [
        {
            "role": "executor",
            "kind": "service",
            "unit": "github-agent-bridge.service",
            "load_state": "loaded",
            "active_state": "active",
            "sub_state": "running",
            "result": "success",
            "exec_main_status": "0",
            "main_pid": 123,
            "uptime_seconds": 90,
            "active_enter_timestamp": "Sat 2026-06-06 09:00:00 UTC",
            "inactive_enter_timestamp": "",
            "next_elapse": "",
            "last_trigger": "",
            "unit_file_state": "enabled",
            "ok": True,
        }
    ]


def test_systemd_status_reports_missing_systemctl(monkeypatch):
    def fake_run(*_args, **_kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(systemd_module, "BRIDGE_UNITS", [systemd_module.BridgeUnit("executor", "service", "GITHUB_AGENT_BRIDGE_EXECUTOR_UNIT", "github-agent-bridge.service")])
    monkeypatch.setattr(systemd_module.subprocess, "run", fake_run)

    status = systemd_module.systemd_status(systemctl_bin="missing-systemctl")

    assert status["available"] is False
    assert status["units"] == []
    assert status["errors"] == ["missing-systemctl not found"]
