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
TOMORROW=$(date -d tomorrow +%Y-%m-%d)
CHAT_ID="${ALLOWED_USER_IDS//[\[\]]/}"

# Trap script errors — send Telegram alert
_send_error() {
    local line=$1 code=$2
    echo "ERROR on line $line (exit $code)"
    if [ -n "$TELEGRAM_BOT_TOKEN" ] && [ -n "$CHAT_ID" ]; then
        curl -s -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/sendMessage" \
            -d "chat_id=$CHAT_ID" \
            -d "text=❌ Вечерний итог упал (строка $line, код $code). Проверь логи: journalctl -u d-brain-evening" \
            > /dev/null || true
    fi
}
trap '_send_error $LINENO $?' ERR

echo "=== d-brain evening summary for $TODAY ==="

cd "$VAULT_DIR"
REPORT=$(claude --print --dangerously-skip-permissions \
    --mcp-config "$PROJECT_DIR/mcp-config.json" \
    -p "Сегодня $TODAY. Сгенерируй вечерний итог дня.

ПОРЯДОК ДЕЙСТВИЙ (выполняй строго по порядку):

1. Получи задачи из Notion базы данных \"Задачи и поручения\".
   Вызови mcp__notion__API-post-database-query с параметрами:
   - database_id: \"305289eb-342c-80ec-856d-f1c014cdff68\"
   - sorts: [{\"timestamp\": \"last_edited_time\", \"direction\": \"descending\"}]
   - page_size: 30
   Раздели задачи на:
   a) Status = \"Done\" — сделано сегодня
   b) Status = \"In progress\" — не завершено
   c) Просроченные — дедлайн < $TODAY и Status != \"Done\"

2. Вызови mcp__google-calendar__list-events для завтра:
   - timeMin: \"${TOMORROW}T00:00:00Z\"
   - timeMax: \"${TOMORROW}T23:59:59Z\"

3. Верни ТОЧНО в таком формате — ничего лишнего, только этот блок:

🌙 <b>Итог дня: $TODAY</b>

✅ <b>Сделано сегодня:</b>
• Название задачи
(или строка «Ничего не закрыто» если пусто)

⏳ <b>В процессе:</b>
• Название задачи
(или пропусти этот блок если нет)

🔴 <b>Просрочено:</b>
• Название задачи (дата)
(или пропусти этот блок если нет)

📅 <b>Завтра в календаре:</b>
• ЧЧ:ММ — Название события
(или строка «Событий нет» если пусто)

ЗАПРЕЩЕНО АБСОЛЮТНО:
- ## или # в начале строки
- ** вокруг текста
- | таблицы |
- --- разделители
- Любой markdown
ТОЛЬКО теги <b> <i> <code> и эмоджи.
Максимум 1500 символов." \
    2>&1) || true
cd "$PROJECT_DIR"

REPORT_CLEAN=$(echo "$REPORT" \
    | sed '/<!--/,/-->/d' \
    | sed 's/^###* //' \
    | sed 's/^## //' \
    | sed 's/^# //' \
    | sed 's/\*\*\(.*\)\*\*/\1/g' \
    | sed 's/\*\([^*]*\)\*/\1/g' \
    | sed '/^---*$/d' \
    | sed '/^|.*|$/d' \
    | sed 's/^\([🌙✅⏳🔴📅]\) \(<b>\)\{0\}\(.*\)$/\1 <b>\3<\/b>/')

# Alert if Claude returned nothing useful
if [ -z "$(echo "$REPORT_CLEAN" | tr -d '[:space:]')" ] && [ -n "$CHAT_ID" ]; then
    curl -s -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/sendMessage" \
        -d "chat_id=$CHAT_ID" \
        -d "text=❌ Вечерний итог: Claude не вернул контент. Проверь логи." \
        > /dev/null || true
fi

if [ -n "$REPORT_CLEAN" ] && [ -n "$CHAT_ID" ]; then
    echo "=== Sending evening summary to Telegram ==="
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

echo "=== Evening summary done ==="
