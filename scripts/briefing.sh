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

# Fetch Gmail, Calendar, Tasks data via Python
BRIEFING_DATA=$(cd "$PROJECT_DIR" && /home/myuser/.local/bin/uv run python3 "$PROJECT_DIR/scripts/briefing_data.py" 2>/dev/null || true)

cd "$VAULT_DIR"
REPORT=$(claude --print --dangerously-skip-permissions \
    --mcp-config "$PROJECT_DIR/mcp-config.json" \
    -p "Сегодня $TODAY. Сгенерируй утренний брифинг из готовых данных.

ВОТ ВСЕ ДАННЫЕ (НЕ вызывай MCP-инструменты, данные уже собраны):

$BRIEFING_DATA

Прочитай файл goals/3-weekly.md

Верни ТОЧНО в таком формате — ничего лишнего, только этот блок:

🌅 <b>Доброе утро! $TODAY</b>

📅 <b>Календарь:</b>
• ЧЧ:ММ — Название события
(или строка «Событий нет» если пусто)

🔴 <b>Просрочено:</b>
• Название задачи (дата)
(или пропусти этот блок если нет)

✅ <b>На сегодня:</b>
• Название задачи
(максимум 7 штук, остальные: «...и ещё N задач»)

📧 <b>Почта:</b>
• Краткое описание важного письма (от кого)
(максимум 5 штук; ИГНОРИРУЙ рассылки, спам, уведомления сервисов; пропусти блок если нет важных)

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
