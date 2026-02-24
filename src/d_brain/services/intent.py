"""Intent classifier for voice/text messages.

Three intents:
  CREATE_TASK   — fast path: create Notion task directly (~200ms)
  NOTION_ACTION — slow path: delegate to Claude with Notion MCP (10-30s)
  SAVE          — default: save to vault as before
"""

import re
from datetime import date, timedelta
from enum import Enum


class Intent(Enum):
    CREATE_TASK = "create_task"
    NOTION_ACTION = "notion_action"
    SAVE = "save"


# ── Intent patterns ────────────────────────────────────────────────────────

_CREATE_PATTERNS = [
    r"\b(добавь|создай|запиши|поставь|внеси)\s+(задачу|задание|напоминание)\b",
    r"\bзадача[:\s]\s*\S",           # "задача: позвонить" or "задача позвонить"
    r"\bнапомни\s+(мне\s+)?о\b",     # "напомни мне о встрече"
]

_ACTION_PATTERNS = [
    # Read / query Notion
    r"\b(покажи|покажи?те|отобрази|выведи|список|какие|что)\s+.{0,30}(задач|задани)",
    r"\bкакие\s+(у меня\s+)?(задач|задани|дела)\b",
    r"\b(просроченн|на сегодня|на завтра|незакрыт|активн|в процессе|не сделан)\b.{0,20}задач",
    r"\bзадач.{0,20}(просроченн|на сегодня|на завтра|незакрыт|активн|в процессе)\b",
    r"\bчто\s+(у меня\s+)?(стоит|есть|висит|осталось)\b",
    r"\bпланы?\s+на\s+(сегодня|завтра|неделю)\b",
    r"\b(найди|найти|поиск)\s+задач",
    # Mark done
    r"\b(отметь|помети|поставь)\s+.{0,40}(выполнен|готов|сделан|закрыт)",
    r"\b(выполнил[аи]?|сделал[аи]?|закрыл[аи]?)\s+(задачу|это|её)\b",
    r"\bзадача\s+.{0,40}\s+(выполнена|готова|сделана|закрыта)\b",
    # Update deadline
    r"\bперенеси\s+.{0,60}\s+на\s+",
    r"\b(измени|обнови|сдвинь)\s+(дедлайн|срок)\b",
    r"\bдедлайн\s+.{0,30}(перенеси|сдвинь|измени|поменяй)\b",
    r"\bпоменяй\s+(дедлайн|срок)\b",
]


def classify(text: str) -> Intent:
    """Classify text intent. Returns Intent enum value."""
    t = text.lower()
    for pattern in _CREATE_PATTERNS:
        if re.search(pattern, t):
            return Intent.CREATE_TASK
    for pattern in _ACTION_PATTERNS:
        if re.search(pattern, t):
            return Intent.NOTION_ACTION
    return Intent.SAVE


# ── Task name extraction ────────────────────────────────────────────────────

_TRIGGER_PREFIX = re.compile(
    r"^(добавь|создай|запиши|поставь|внеси)\s+(задачу|задание|напоминание)[:\s]*",
    re.IGNORECASE,
)
_TASK_PREFIX = re.compile(r"^задач[уа][:\s]*", re.IGNORECASE)


def extract_task_name(text: str) -> str:
    """Strip intent trigger words and return the task name."""
    t = text.strip()
    t = _TRIGGER_PREFIX.sub("", t)
    t = _TASK_PREFIX.sub("", t)
    return t.strip()


# ── Due date extraction ─────────────────────────────────────────────────────

_TODAY_RE = re.compile(r"\bсегодня\b", re.IGNORECASE)
_TOMORROW_RE = re.compile(r"\bзавтра\b", re.IGNORECASE)
_DATE_RE = re.compile(r"\b(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?\b")
_WEEKDAY_RE = re.compile(
    r"\b(понедельник|вторник|среду?|четверг|пятницу?|субботу?|воскресенье)\b",
    re.IGNORECASE,
)

_WEEKDAY_MAP = {
    "понедельник": 0, "вторник": 1, "среда": 1, "среду": 2,
    "четверг": 3, "пятница": 4, "пятницу": 4,
    "суббота": 5, "субботу": 5, "воскресенье": 6,
}


def extract_due_date(text: str) -> str | None:
    """Try to detect a due date hint and return ISO date string or None."""
    today = date.today()

    if _TODAY_RE.search(text):
        return today.isoformat()

    if _TOMORROW_RE.search(text):
        return (today + timedelta(days=1)).isoformat()

    m = _WEEKDAY_RE.search(text.lower())
    if m:
        target_wd = _WEEKDAY_MAP.get(m.group(1).lower())
        if target_wd is not None:
            days_ahead = (target_wd - today.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7  # "в пятницу" means next Friday if today is Friday
            return (today + timedelta(days=days_ahead)).isoformat()

    m2 = _DATE_RE.search(text)
    if m2:
        day, month = int(m2.group(1)), int(m2.group(2))
        year_raw = m2.group(3)
        year = int(year_raw) if year_raw else today.year
        if year < 100:
            year += 2000
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            pass

    return None
