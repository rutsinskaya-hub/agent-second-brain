#!/bin/bash
set -e

# PATH for systemd
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
export HOME="/home/myuser"

PROJECT_DIR="/home/myuser/projects/agent-second-brain"
VAULT_DIR="$PROJECT_DIR/vault"
ENV_FILE="$PROJECT_DIR/.env"

if [ -f "$ENV_FILE" ]; then
    export $(grep -v '^#' "$ENV_FILE" | xargs)
fi

if [ -z "$TELEGRAM_BOT_TOKEN" ]; then
    echo "ERROR: TELEGRAM_BOT_TOKEN not set"
    exit 1
fi

export MCP_TIMEOUT=30000
export MAX_MCP_OUTPUT_TOKENS=50000
export GOOGLE_OAUTH_CREDENTIALS="$PROJECT_DIR/gcp-oauth.keys.json"

TODAY=$(date +%Y-%m-%d)
CHAT_ID="${ALLOWED_USER_IDS//[\[\]]/}"

echo "=== d-brain morning briefing for $TODAY ==="

cd "$VAULT_DIR"
REPORT=$(claude --print --dangerously-skip-permissions \
    --mcp-config "$PROJECT_DIR/mcp-config.json" \
    -p "Сегодня $TODAY. Сгенерируй утренний брифинг.

ПОРЯДОК ДЕЙСТВИЙ:
1. Вызови mcp__google-calendar__list-events для today (с $TODAY 00:00 по $TODAY 23:59)
2. Получи задачи из Notion на сегодня
3. Прочитай vault/goals/3-weekly.md — что ONE Big Thing этой недели?
4. Составь краткий HTML отчёт

ФОРМАТ ОТЧЁТА (только HTML для Telegram):
🌅 <b>Доброе утро! $TODAY</b>

📅 <b>Сегодня в календаре:</b>
[список событий с временем, или «Событий нет»]

✅ <b>Задачи на сегодня:</b>
[задачи из Notion]

🎯 <b>Главное на неделю:</b>
[ONE Big Thing из goals/3-weekly.md]

ПРАВИЛА:
- Только теги: <b>, <i>, <code>
- Без markdown (**, ##, ---)
- Максимум 2000 символов
- Если MCP не отвечает сразу — подожди 10 сек и попробуй снова" \
    2>&1) || true
cd "$PROJECT_DIR"

REPORT_CLEAN=$(echo "$REPORT" | sed '/<!--/,/-->/d')

if [ -n "$REPORT_CLEAN" ] && [ -n "$CHAT_ID" ]; then
    echo "=== Sending briefing to Telegram ==="
    RESULT=$(curl -s -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/sendMessage" \
        -d "chat_id=$CHAT_ID" \
        -d "text=$REPORT_CLEAN" \
        -d "parse_mode=HTML")

    if echo "$RESULT" | grep -q '"ok":false'; then
        echo "HTML failed, sending plain: $RESULT"
        curl -s -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/sendMessage" \
            -d "chat_id=$CHAT_ID" \
            -d "text=$REPORT_CLEAN"
    fi
fi

echo "=== Briefing done ==="
