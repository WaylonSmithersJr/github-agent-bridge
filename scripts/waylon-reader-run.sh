#!/usr/bin/env bash
set -euo pipefail

cd /home/clawbot/.openclaw/workspace/github-agent-bridge
set -a
source /home/clawbot/.config/github-agent-bridge/env
set +a
exec /home/clawbot/.openclaw/workspace/github-agent-bridge/.venv/bin/github-agent-bridge-reader-run
