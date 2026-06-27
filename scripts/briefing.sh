#!/bin/bash
set -e

export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
export HOME="/home/myuser"

PROJECT_DIR="/home/myuser/projects/agent-second-brain"
ENV_FILE="$PROJECT_DIR/.env"

if [ -f "$ENV_FILE" ]; then
    export $(grep -v '^#' "$ENV_FILE" | xargs)
fi

if [ -z "$TELEGRAM_BOT_TOKEN" ]; then
    echo "ERROR: TELEGRAM_BOT_TOKEN not set"; exit 1
fi

TODAY=$(date +%Y-%m-%d)
CHAT_ID="${ALLOWED_USER_IDS//[\[\]]/}"

send() { curl -s -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/sendMessage" "$@"; }

_send_error() {
    local line=$1 code=$2
    echo "ERROR on line $line (exit $code)"
    [ -n "$CHAT_ID" ] && send -d "chat_id=$CHAT_ID" \
        --data-urlencode "text=❌ Утренний брифинг упал (строка $line, код $code). journalctl -u d-brain-briefing" >/dev/null || true
}
trap '_send_error $LINENO $?' ERR

echo "=== d-brain morning briefing for $TODAY ==="

# Детерминированная сборка отчёта в Python (без Claude/sed) — готовый Telegram-HTML
REPORT=$(cd "$PROJECT_DIR" && /home/myuser/.local/bin/uv run python3 "$PROJECT_DIR/scripts/briefing_data.py" 2>/tmp/briefing.err)

if [ -z "$(echo "$REPORT" | tr -d '[:space:]')" ]; then
    [ -n "$CHAT_ID" ] && send -d "chat_id=$CHAT_ID" \
        --data-urlencode "text=❌ Брифинг: пустой отчёт. Проверь: cat /tmp/briefing.err" >/dev/null || true
    exit 0
fi

echo "=== Sending briefing to Telegram ==="
RESULT=$(send -d "chat_id=$CHAT_ID" --data-urlencode "text=$REPORT" -d "parse_mode=HTML")
if echo "$RESULT" | grep -q '"ok":false'; then
    echo "HTML failed, sending plain: $RESULT"
    send -d "chat_id=$CHAT_ID" --data-urlencode "text=$REPORT" >/dev/null
fi

echo "=== Briefing done ==="
