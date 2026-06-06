#!/usr/bin/env bash
set -euo pipefail

cd /home/clawbot/.openclaw/workspace/github-agent-bridge
set -a
source /home/clawbot/.config/github-agent-bridge/env
set +a

exec /home/clawbot/.openclaw/workspace/github-agent-bridge/.venv/bin/gab \
  --db /home/clawbot/.local/state/github-agent-bridge/bridge.sqlite3 \
  --policy /home/clawbot/.config/github-agent-bridge/policy.json \
  run \
  --mode "${GITHUB_AGENT_BRIDGE_MODE:-shadow}" \
  --workers "${GITHUB_AGENT_BRIDGE_WORKERS:-2}" \
  --gh-bin "${GITHUB_AGENT_BRIDGE_GH_BIN:-gh}" \
  --openclaw-bin "${GITHUB_AGENT_BRIDGE_OPENCLAW_BIN:-openclaw}" \
  --node-bin "${GITHUB_AGENT_BRIDGE_NODE_BIN:-}" \
  --channel "${GITHUB_AGENT_BRIDGE_DEFAULT_CHANNEL:-telegram}" \
  --to "${GITHUB_AGENT_BRIDGE_DEFAULT_TO:-}"
