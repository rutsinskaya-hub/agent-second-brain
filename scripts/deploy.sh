#!/usr/bin/env bash
# Safe deploy for agent-second-brain.
# ALWAYS pulls/syncs as myuser so vault files never become root-owned (Errno 13 fix).
# Run from root via SSH:  bash /home/myuser/projects/agent-second-brain/scripts/deploy.sh
set -euo pipefail
PROJ=/home/myuser/projects/agent-second-brain
UV=/home/myuser/.local/bin/uv

# Code update as myuser — NEVER as root. --autostash is a safety net only.
sudo -u myuser bash -lc "cd '$PROJ' && git -c safe.directory='*' pull --autostash origin main && '$UV' sync"

# Only the restart needs root.
systemctl restart d-brain-bot
sleep 2
echo "deploy done: d-brain-bot is $(systemctl is-active d-brain-bot)"
