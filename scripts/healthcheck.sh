#!/bin/bash
set -e
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
export HOME="/home/myuser"
PROJECT_DIR="/home/myuser/projects/agent-second-brain"
[ -f "$PROJECT_DIR/.env" ] && export $(grep -v '^#' "$PROJECT_DIR/.env" | xargs)
cd "$PROJECT_DIR" && /home/myuser/.local/bin/uv run python3 "$PROJECT_DIR/scripts/healthcheck.py"
