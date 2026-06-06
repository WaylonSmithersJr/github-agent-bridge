from __future__ import annotations

import os
import sys

from .cli import DEFAULT_DB, DEFAULT_POLICY, main as cli_main
from .reader import imap_mailbox_arg


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def main() -> int:
    """Run one reader pass from GITHUB_AGENT_BRIDGE_* environment.

    This small wrapper keeps the systemd unit simple, especially for optional
    mutation flags, which should be omitted completely in shadow deployments.
    """
    source = env("GITHUB_AGENT_BRIDGE_READER_SOURCE", "imap").lower()
    if source == "github":
        argv = [
            "--db",
            env("GITHUB_AGENT_BRIDGE_DB", DEFAULT_DB),
            "--policy",
            env("GITHUB_AGENT_BRIDGE_POLICY", DEFAULT_POLICY),
            "read-github-notifications-once",
            "--gh-bin",
            env("GITHUB_AGENT_BRIDGE_GH_BIN", "gh"),
        ]
        if env("GITHUB_AGENT_BRIDGE_GITHUB_ALL") in {"1", "true", "TRUE", "yes", "YES", "--all"}:
            argv.append("--all")
        if env("GITHUB_AGENT_BRIDGE_GITHUB_PARTICIPATING") in {"1", "true", "TRUE", "yes", "YES", "--participating"}:
            argv.append("--participating")
        if env("GITHUB_AGENT_BRIDGE_MARK_READ") in {"1", "true", "TRUE", "yes", "YES", "--mark-read"}:
            argv.append("--mark-read")
        return cli_main(argv)

    if source != "imap":
        print("GITHUB_AGENT_BRIDGE_READER_SOURCE must be 'imap' or 'github'", file=sys.stderr)
        return 2

    missing = [name for name in ("GITHUB_AGENT_BRIDGE_EMAIL", "GITHUB_AGENT_BRIDGE_PASSWORD") if not env(name)]
    if missing:
        print(f"missing required environment variables: {', '.join(missing)}", file=sys.stderr)
        return 2

    argv = [
        "--db",
        env("GITHUB_AGENT_BRIDGE_DB", DEFAULT_DB),
        "--policy",
        env("GITHUB_AGENT_BRIDGE_POLICY", DEFAULT_POLICY),
        "read-imap-once",
        "--imap-host",
        env("GITHUB_AGENT_BRIDGE_IMAP_HOST", "imap.gmail.com"),
        "--imap-port",
        env("GITHUB_AGENT_BRIDGE_IMAP_PORT", "993"),
        "--email",
        env("GITHUB_AGENT_BRIDGE_EMAIL"),
        "--password",
        env("GITHUB_AGENT_BRIDGE_PASSWORD"),
        "--mailbox",
        imap_mailbox_arg(env("GITHUB_AGENT_BRIDGE_MAILBOX", "INBOX")),
    ]
    if env("GITHUB_AGENT_BRIDGE_MARK_SEEN") in {"1", "true", "TRUE", "yes", "YES", "--mark-seen"}:
        argv.append("--mark-seen")
    return cli_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
