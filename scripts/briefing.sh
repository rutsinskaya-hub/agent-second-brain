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

# Trap script errors — send Telegram alert
_send_error() {
    local line=$1 code=$2
    echo "ERROR on line $line (exit $code)"
    if [ -n "$TELEGRAM_BOT_TOKEN" ] && [ -n "$CHAT_ID" ]; then
        curl -s -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/sendMessage" \
            -d "chat_id=$CHAT_ID" \
            -d "text=❌ Брифинг упал (строка $line, код $code). Проверь логи: journalctl -u d-brain-briefing" \
            > /dev/null || true
    fi
}
trap '_send_error $LINENO $?' ERR

echo "=== d-brain morning briefing for $TODAY ==="

# Fetch Gmail data (silent if not configured)
GMAIL_DATA=$(python3 "$PROJECT_DIR/scripts/gmail_fetch.py" 2>/dev/null || true)

# Build Gmail prompt section
GMAIL_SECTION=""
if [ -n "$GMAIL_DATA" ]; then
    GMAIL_SECTION="
3. Вот данные из Gmail:
$GMAIL_DATA
Проанализируй письма. ИГНОРИРУЙ рассылки, уведомления сервисов, спам.
Из важных писем покажи краткую сводку в секции «📧 Почта».
"
fi

cd "$VAULT_DIR"
REPORT=$(claude --print --dangerously-skip-permissions \
    --mcp-config "$PROJECT_DIR/mcp-config.json" \
    -p "Сегодня $TODAY. Сгенерируй утренний брифинг.

ПОРЯДОК ДЕЙСТВИЙ (выполняй строго по порядку):

1. Вызови mcp__google-calendar__list-events с параметрами:
   - timeMin: \"${TODAY}T00:00:00Z\"
   - timeMax: \"${TODAY}T23:59:59Z\"

2. Получи задачи из Notion базы данных \"Задачи и поручения\".
   Вызови mcp__notion__API-post-database-query с параметрами:
   - database_id: \"305289eb-342c-80ec-856d-f1c014cdff68\"
   - filter: {\"property\": \"Status\", \"status\": {\"does_not_equal\": \"Done\"}}
   - sorts: [{\"property\": \"Срок выполнения\", \"direction\": \"ascending\"}]
   - page_size: 20
   Показывай задачи в таком приоритете:
   a) Срок выполнения = сегодня ($TODAY)
   b) Status = "In progress"
   c) Если ничего — топ-5 задач со статусом "Not started"
   Не показывай задачи со статусом "Done".
$GMAIL_SECTION
Прочитай файл goals/3-weekly.md

Верни ТОЧНО в таком формате — ничего лишнего, только этот блок:

🌅 <b>Доброе утро! $TODAY</b>

📅 <b>Календарь:</b>
• ЧЧ:ММ — Название события
• ЧЧ:ММ — Название события
(или строка «Событий нет» если пусто)

🔴 <b>Просрочено:</b>
• Название задачи (дата)
(или пропусти этот блок если нет)

✅ <b>На сегодня:</b>
• Название задачи
• Название задачи
(максимум 7 штук, остальные: «...и ещё N задач»)

📧 <b>Почта:</b>
• Краткое описание важного письма (от кого)
(максимум 5 штук, пропусти блок если нет важных писем или Gmail не подключён)

🎯 <b>ONE Big Thing:</b>
Текст цели из goals/3-weekly.md

💪 <b>Process goals:</b>
• Цель 1
• Цель 2

ЗАПРЕЩЕНО АБСОЛЮТНО:
- ## или # в начале строки
- ** вокруг текста
- | таблицы |
- --- разделители
- Любой markdown
ТОЛЬКО теги <b> <i> <code> и эмоджи.
Максимум 2500 символов." \
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
    | sed 's/^\(🌅[^<]*\)$/\1/' \
    | sed 's/^\([📅🔴✅🎯💪🗓️⬜]\) \(<b>\)\{0\}\(.*\)$/\1 <b>\3<\/b>/')

# Alert if Claude returned nothing useful
if [ -z "$(echo "$REPORT_CLEAN" | tr -d '[:space:]')" ] && [ -n "$CHAT_ID" ]; then
    curl -s -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/sendMessage" \
        -d "chat_id=$CHAT_ID" \
        -d "text=❌ Брифинг: Claude не вернул контент. Проверь логи." \
        > /dev/null || true
fi

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
