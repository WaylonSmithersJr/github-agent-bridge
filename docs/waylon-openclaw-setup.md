# WaylonSmithersJr OpenClaw Setup

This fork can read GitHub notifications directly through `gh api notifications`.
That is the preferred path for the WaylonSmithersJr deployment because the
assistant's Proton account is a free Proton Mail account and does not support
Proton Bridge IMAP.

## Why GitHub Notifications API

- No IMAP or Proton Bridge required.
- Uses the authenticated GitHub account already configured in `gh`.
- Preserves the existing bridge pipeline:
  `GitHub notification -> Notification -> Policy -> SQLite queue -> OpenClaw dispatch`.
- Can start in `shadow` without reacting to GitHub, marking notifications read,
  or dispatching live work.

## Local Bootstrap

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
pytest -q
```

Create local state:

```bash
mkdir -p ~/.config/github-agent-bridge ~/.local/state/github-agent-bridge
chmod 700 ~/.config/github-agent-bridge ~/.local/state/github-agent-bridge
cp policy.waylon.example.json ~/.config/github-agent-bridge/policy.json
chmod 600 ~/.config/github-agent-bridge/policy.json
gab --db ~/.local/state/github-agent-bridge/bridge.sqlite3 init-db
```

Create the environment file used by the packaged reader wrapper:

```bash
cat > ~/.config/github-agent-bridge/env <<'EOF'
GITHUB_AGENT_BRIDGE_READER_SOURCE=github
GITHUB_AGENT_BRIDGE_GH_BIN=gh
GITHUB_AGENT_BRIDGE_MODE=shadow
GITHUB_AGENT_BRIDGE_MARK_READ=
GITHUB_AGENT_BRIDGE_DEFAULT_CHANNEL=telegram
GITHUB_AGENT_BRIDGE_DEFAULT_TO=telegram:345504031
EOF
chmod 600 ~/.config/github-agent-bridge/env
```

Read GitHub notifications without side effects:

```bash
gab \
  --db ~/.local/state/github-agent-bridge/bridge.sqlite3 \
  --policy ~/.config/github-agent-bridge/policy.json \
  read-github-notifications-once --verbose
```

Process exactly one queued job in `shadow`:

```bash
gab \
  --db ~/.local/state/github-agent-bridge/bridge.sqlite3 \
  --policy ~/.config/github-agent-bridge/policy.json \
  run --mode shadow --once
```

Install the Waylon user services:

```bash
chmod +x scripts/waylon-reader-run.sh scripts/waylon-executor-run.sh
mkdir -p ~/.config/systemd/user
cp systemd/waylon-github-agent-bridge*.service ~/.config/systemd/user/
cp systemd/waylon-github-agent-bridge-reader.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now waylon-github-agent-bridge-reader.timer
systemctl --user enable --now waylon-github-agent-bridge.service
```

Only after shadow behavior is clean, add `--mark-read` to the reader and move the
executor to a controlled canary `live` run.

## Commands

```bash
# Unread notifications only, no side effects:
gab ... read-github-notifications-once --verbose

# Include read notifications for debugging/replay:
gab ... read-github-notifications-once --all --verbose

# Mark threads read after enqueue/dedup/coalesce:
gab ... read-github-notifications-once --mark-read
```

## Safety Defaults

- Keep `enabledRepos` narrow.
- Keep `run --mode shadow` until a canary repo behaves correctly.
- Do not use `--mark-read` until this bridge owns GitHub notification handling.
- Keep `botLogins` set to `WaylonSmithersJr`.
