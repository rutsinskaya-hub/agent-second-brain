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

ПОРЯДОК ДЕЙСТВИЙ (выполняй строго по порядку):

1. Вызови mcp__google-calendar__list-events с параметрами:
   - timeMin: \"${TODAY}T00:00:00Z\"
   - timeMax: \"${TODAY}T23:59:59Z\"

2. Вызови mcp__notion__API-post-search с filter={\"property\":\"object\",\"value\":\"page\"} и query=\"задачи сегодня\" чтобы найти задачи на сегодня. Если не нашёл — попробуй query=\"todo\" или query=\"задачи\".

3. Прочитай файл goals/3-weekly.md

4. Составь HTML отчёт в формате ниже.

ФОРМАТ ОТЧЁТА (ТОЛЬКО HTML для Telegram, никакого markdown):
🌅 <b>Доброе утро! $TODAY</b>

📅 <b>Календарь на сегодня:</b>
[каждое событие с <b>временем</b> — название]
[если нет — «Событий нет»]

✅ <b>Задачи из Notion:</b>
[список задач из найденных страниц]
[если нет — «Задач нет»]

🎯 <b>Главное на неделю:</b>
[ONE Big Thing из goals/3-weekly.md]

ПРАВИЛА:
- Только теги: <b>, <i>, <code>
- Без **, ##, ---, таблиц
- Максимум 2000 символов
- MCP может грузиться 10-30 сек — подожди и вызови снова если ошибка" \
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
