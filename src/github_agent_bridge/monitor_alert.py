from __future__ import annotations

import hashlib
import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AlertConfig:
    bridge_bin: str
    openclaw_bin: str
    db: str
    policy: str
    channel: str
    target: str
    state_dir: Path
    resend_seconds: int
    auto_unlock_seconds: int | None
    pending_warn_seconds: int
    review_running_warn_seconds: int
    work_running_warn_seconds: int

    @property
    def state_file(self) -> Path:
        return self.state_dir / "monitor-alert.state"

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> AlertConfig:
        values = env or os.environ
        state_dir = Path(values.get("GITHUB_AGENT_BRIDGE_STATE_DIR", "~/.local/state/github-agent-bridge")).expanduser()
        return cls(
            bridge_bin=values.get("GITHUB_AGENT_BRIDGE_BIN", "~/.local/bin/github-agent-bridge"),
            openclaw_bin=values.get("GITHUB_AGENT_BRIDGE_OPENCLAW_BIN", "~/.nvm/versions/node/v24.14.0/bin/openclaw"),
            db=values.get("GITHUB_AGENT_BRIDGE_DB", "~/.local/state/github-agent-bridge/bridge.sqlite3"),
            policy=values.get("GITHUB_AGENT_BRIDGE_POLICY", "~/.config/github-agent-bridge/policy.json"),
            channel=values.get("GITHUB_AGENT_BRIDGE_ALERT_CHANNEL", "telegram"),
            target=values.get("GITHUB_AGENT_BRIDGE_ALERT_TO", "43532269"),
            state_dir=state_dir,
            resend_seconds=int(values.get("GITHUB_AGENT_BRIDGE_ALERT_RESEND_SECONDS", "900")),
            auto_unlock_seconds=_parse_optional_int(values.get("GITHUB_AGENT_BRIDGE_AUTO_UNLOCK_STALE_SECONDS", "900")),
            pending_warn_seconds=int(values.get("GITHUB_AGENT_BRIDGE_PENDING_WARN_SECONDS", "300")),
            review_running_warn_seconds=int(values.get("GITHUB_AGENT_BRIDGE_REVIEW_RUNNING_WARN_SECONDS", "600")),
            work_running_warn_seconds=int(values.get("GITHUB_AGENT_BRIDGE_WORK_RUNNING_WARN_SECONDS", "900")),
        )


def _parse_optional_int(value: str | None) -> int | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    return int(value)


def _expand(path: str) -> str:
    return os.path.expanduser(path)


def _run(args: list[str], check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=check, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def run_monitor(config: AlertConfig) -> subprocess.CompletedProcess[str]:
    return _run(
        [
            _expand(config.bridge_bin),
            "--db",
            _expand(config.db),
            "--policy",
            _expand(config.policy),
            "monitor",
            "--pending-warn-seconds",
            str(config.pending_warn_seconds),
            "--review-running-warn-seconds",
            str(config.review_running_warn_seconds),
            "--work-running-warn-seconds",
            str(config.work_running_warn_seconds),
        ]
    )


def get_main_pid(unit: str = "github-agent-bridge.service") -> str:
    proc = _run(["systemctl", "--user", "show", unit, "--property=MainPID", "--value"])
    return (proc.stdout or "").strip()


def has_child_processes(pid: str) -> bool:
    proc = subprocess.run(["pgrep", "-P", pid], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=False)
    return proc.returncode == 0


def maybe_unlock_stale(config: AlertConfig, output: str) -> str:
    if config.auto_unlock_seconds is None or "running job " not in output:
        return ""
    main_pid = get_main_pid()
    if not main_pid or main_pid == "0" or has_child_processes(main_pid):
        return ""
    proc = _run(
        [
            _expand(config.bridge_bin),
            "--db",
            _expand(config.db),
            "--policy",
            _expand(config.policy),
            "unlock-stale",
            "--older-than",
            str(config.auto_unlock_seconds),
        ]
    )
    return proc.stdout


def load_state(path: Path) -> tuple[str, int]:
    if not path.exists():
        return "", 0
    text = path.read_text(encoding="utf-8")
    hash_match = re.search(r"LAST_HASH='([^']*)'", text)
    ts_match = re.search(r"LAST_TS=(\d+)", text)
    if hash_match and ts_match:
        return hash_match.group(1), int(ts_match.group(1))
    parts = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
    return parts.get("LAST_HASH", ""), int(parts.get("LAST_TS", "0") or "0")


def save_state(path: Path, alert_hash: str, now: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"LAST_HASH='{alert_hash}'\nLAST_TS={now}\n", encoding="utf-8")


def should_send_alert(path: Path, output: str, resend_seconds: int, now: int | None = None) -> bool:
    now = int(time.time() if now is None else now)
    alert_hash = hashlib.sha256(output.encode("utf-8")).hexdigest()
    last_hash, last_ts = load_state(path)
    if alert_hash == last_hash and (now - last_ts) < resend_seconds:
        return False
    save_state(path, alert_hash, now)
    return True


def send_alert(config: AlertConfig, output: str, unlock_output: str) -> None:
    _run(
        [
            _expand(config.openclaw_bin),
            "message",
            "send",
            "--channel",
            config.channel,
            "--target",
            config.target,
            "--message",
            f"GitHub bridge ALERTA\n\n{output}\n\n{unlock_output}",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    del argv
    config = AlertConfig.from_env()
    config.state_dir.mkdir(parents=True, exist_ok=True)

    monitor_proc = run_monitor(config)
    output = monitor_proc.stdout
    print(output, end="" if output.endswith("\n") else "\n")

    if monitor_proc.returncode == 0:
        config.state_file.unlink(missing_ok=True)
        return 0

    unlock_output = maybe_unlock_stale(config, output)
    if unlock_output:
        print(unlock_output, end="" if unlock_output.endswith("\n") else "\n")

    if not should_send_alert(config.state_file, output, config.resend_seconds):
        return 0

    send_alert(config, output, unlock_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
