# Installation guide

This guide shows how to install `github-agent-bridge` for a new OpenClaw deployment.

## Prerequisites

Before installing the bridge, have these ready:

- Python 3.11 or newer.
- OpenClaw CLI installed and able to run `openclaw agent`.
- GitHub CLI (`gh`) installed and authenticated as the GitHub user/bot that should react to comments.
- An email inbox that receives GitHub notification emails.
- IMAP access to that inbox, usually an app password.
- A delivery route for OpenClaw agent work, for example a Telegram chat id, Discord channel, or another OpenClaw-supported channel.
- Optional but recommended: user-level systemd for the executor, reader timer, and monitor timer.

## Install the CLI

Install from GitHub. There is no PyPI publish yet.

```bash
python3 -m pip install --user \
  'git+https://github.com/pilipilisbot/github-agent-bridge.git'
```

Make sure the script directory is on `PATH`:

```bash
export PATH="$HOME/.local/bin:$PATH"
gab --help
```

For a pinned install, use a release tag:

```bash
python3 -m pip install --user \
  'git+https://github.com/pilipilisbot/github-agent-bridge.git@v0.5.7'
```

## Create runtime directories

```bash
mkdir -p ~/.config/github-agent-bridge
mkdir -p ~/.local/state/github-agent-bridge
chmod 700 ~/.config/github-agent-bridge ~/.local/state/github-agent-bridge
```

Initialize the SQLite database:

```bash
gab --db ~/.local/state/github-agent-bridge/bridge.sqlite3 init-db
```

## Configure policy

Start from the example policy:

```bash
curl -fsSL \
  https://raw.githubusercontent.com/pilipilisbot/github-agent-bridge/main/policy.example.json \
  -o ~/.config/github-agent-bridge/policy.json
chmod 600 ~/.config/github-agent-bridge/policy.json
```

Edit at least these fields:

```json
{
  "trustedOrgs": ["your-org"],
  "enabledRepos": ["your-org/your-repo"],
  "orgRoutes": {
    "your-org": {
      "agent": "your-openclaw-agent",
      "channel": "telegram",
      "to": "YOUR_CHAT_ID"
    }
  },
  "repoRoles": {
    "your-org/your-repo": "maintainer"
  }
}
```

Use `enabledRepos` as the live canary allowlist. Keep it narrow until behavior is clean.

## Configure environment

Create a private environment file:

```bash
cat > ~/.config/github-agent-bridge/env <<'EOF_ENV'
GITHUB_AGENT_BRIDGE_MODE=shadow
GITHUB_AGENT_BRIDGE_WORKERS=2
GITHUB_AGENT_BRIDGE_REVIEW_TIMEOUT=900
GITHUB_AGENT_BRIDGE_WORK_TIMEOUT=3600
GITHUB_AGENT_BRIDGE_OPENCLAW_BIN=openclaw
GITHUB_AGENT_BRIDGE_NODE_BIN=
GITHUB_AGENT_BRIDGE_DEFAULT_CHANNEL=telegram
GITHUB_AGENT_BRIDGE_DEFAULT_TO=

GITHUB_AGENT_BRIDGE_EMAIL=you@example.com
GITHUB_AGENT_BRIDGE_PASSWORD=imap-app-password
GITHUB_AGENT_BRIDGE_IMAP_HOST=imap.gmail.com
GITHUB_AGENT_BRIDGE_IMAP_PORT=993
GITHUB_AGENT_BRIDGE_MAILBOX=INBOX
GITHUB_AGENT_BRIDGE_MARK_SEEN=
EOF_ENV
chmod 600 ~/.config/github-agent-bridge/env
```

Leave `GITHUB_AGENT_BRIDGE_MARK_SEEN` empty until the bridge owns GitHub notification handling for that inbox.

If `openclaw` is not on the systemd PATH, set `GITHUB_AGENT_BRIDGE_OPENCLAW_BIN` to the absolute path from `command -v openclaw`.

## Validate without side effects

First enqueue a known GitHub comment URL and process it in shadow mode:

```bash
gab --db ~/.local/state/github-agent-bridge/bridge.sqlite3 \
  --policy ~/.config/github-agent-bridge/policy.json \
  enqueue-comment-url 'https://github.com/your-org/your-repo/pull/123#issuecomment-456'

gab --db ~/.local/state/github-agent-bridge/bridge.sqlite3 \
  --policy ~/.config/github-agent-bridge/policy.json \
  run --mode shadow --once
```

Then read the inbox once without marking messages seen:

```bash
set -a
. ~/.config/github-agent-bridge/env
set +a

gab --db ~/.local/state/github-agent-bridge/bridge.sqlite3 \
  --policy ~/.config/github-agent-bridge/policy.json \
  read-imap-once \
  --imap-host "$GITHUB_AGENT_BRIDGE_IMAP_HOST" \
  --imap-port "$GITHUB_AGENT_BRIDGE_IMAP_PORT" \
  --email "$GITHUB_AGENT_BRIDGE_EMAIL" \
  --password "$GITHUB_AGENT_BRIDGE_PASSWORD" \
  --mailbox "$GITHUB_AGENT_BRIDGE_MAILBOX"

gab --db ~/.local/state/github-agent-bridge/bridge.sqlite3 jobs --limit 20
```

## Run manually

Run the executor in shadow mode first:

```bash
gab --db ~/.local/state/github-agent-bridge/bridge.sqlite3 \
  --policy ~/.config/github-agent-bridge/policy.json \
  run --mode shadow --workers 2
```

When the canary is clean, switch to live:

```bash
gab --db ~/.local/state/github-agent-bridge/bridge.sqlite3 \
  --policy ~/.config/github-agent-bridge/policy.json \
  run --mode live --workers 2
```

Run the reader separately. Add `--mark-seen` only when the bridge should consume GitHub notifications from the inbox:

```bash
gab --db ~/.local/state/github-agent-bridge/bridge.sqlite3 \
  --policy ~/.config/github-agent-bridge/policy.json \
  read-imap-once \
  --email "$GITHUB_AGENT_BRIDGE_EMAIL" \
  --password "$GITHUB_AGENT_BRIDGE_PASSWORD" \
  --mark-seen
```

## Install user systemd units

Clone the repository if you did not keep a checkout, because the systemd unit files are not installed by `pip`:

```bash
git clone https://github.com/pilipilisbot/github-agent-bridge.git /tmp/github-agent-bridge
cd /tmp/github-agent-bridge
```

Install the units:

```bash
mkdir -p ~/.config/systemd/user
cp systemd/github-agent-bridge.service ~/.config/systemd/user/
cp systemd/github-agent-bridge-reader.service ~/.config/systemd/user/
cp systemd/github-agent-bridge-reader.timer ~/.config/systemd/user/
cp systemd/github-agent-bridge-monitor.service ~/.config/systemd/user/
cp systemd/github-agent-bridge-monitor.timer ~/.config/systemd/user/

systemctl --user daemon-reload
systemctl --user enable --now github-agent-bridge.service
systemctl --user enable --now github-agent-bridge-reader.timer
systemctl --user enable --now github-agent-bridge-monitor.timer
```

Inspect status and logs:

```bash
systemctl --user status github-agent-bridge.service
systemctl --user status github-agent-bridge-reader.timer
journalctl --user -u github-agent-bridge.service -f
```

## Monitor health

```bash
gab --db ~/.local/state/github-agent-bridge/bridge.sqlite3 \
  --policy ~/.config/github-agent-bridge/policy.json \
  monitor

gab --db ~/.local/state/github-agent-bridge/bridge.sqlite3 status
```

A healthy install has no old pending jobs, no blocked dispatches, and no stale running jobs.

## Go live safely

1. Keep `GITHUB_AGENT_BRIDGE_MODE=shadow` until shadow jobs look correct.
2. Keep `enabledRepos` to one canary repository.
3. Switch the executor to `GITHUB_AGENT_BRIDGE_MODE=live`.
4. Keep `GITHUB_AGENT_BRIDGE_MARK_SEEN` empty until the reader behavior is clean.
5. Set `GITHUB_AGENT_BRIDGE_MARK_SEEN=--mark-seen` only when this bridge is the GitHub notification owner.
6. Widen `enabledRepos`, `trustedRepos`, or `trustedOrgs` gradually.

## Reusability status

The bridge is reusable by another OpenClaw operator, but it is not a standalone SaaS and it is not yet a one-command installer.

Reusable today:

- packaged Python CLI (`gab`),
- SQLite queue and monitor,
- JSON policy model,
- prompt resources and repository roles,
- systemd unit templates,
- shadow/dry-run/live rollout modes.

Deployment-specific setup still required:

- OpenClaw agent ids and delivery routes,
- GitHub bot/user authentication through `gh`,
- IMAP mailbox credentials,
- trusted org/repo policy,
- systemd paths and environment values.
