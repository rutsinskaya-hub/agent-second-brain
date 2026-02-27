"""Intent classifier for voice/text messages.

Three intents:
  CREATE_TASK   — fast path: create Notion task directly (~200ms)
  NOTION_ACTION — slow path: delegate to Claude with Notion MCP (10-30s)
  SAVE          — default: save to vault as before
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from enum import Enum


class Intent(Enum):
    CREATE_TASK = "create_task"
    QUERY_TASKS = "query_tasks"    # Fast: read from Notion API directly
    NOTION_ACTION = "notion_action"  # Slow: update/write via Claude + MCP
    SAVE = "save"


class QueryType(Enum):
    OVERDUE = "overdue"
    TODAY = "today"
    TOMORROW = "tomorrow"
    IN_PROGRESS = "in_progress"
    ALL = "all"


# ── Intent patterns ────────────────────────────────────────────────────────

_CREATE_PATTERNS = [
    r"\b(добавь|создай|запиши|поставь|внеси)\s+(задачу|задание|напоминание)\b",
    r"\bзадача[:\s]\s*\S",           # "задача: позвонить" or "задача позвонить"
    r"\bнапомни\s+(мне\s+)?о\b",     # "напомни мне о встрече"
]

_QUERY_PATTERNS = [
    r"\b(покажи|покажи?те|отобрази|выведи|список)\s+.{0,30}(задач|задани)",
    r"\bкакие\s+(у меня\s+)?(задач|задани|дела)\b",
    r"\b(просроченн|незакрыт|активн|не сделан)\b.{0,20}задач",
    r"\bзадач.{0,20}(просроченн|незакрыт|активн)\b",
    r"\bчто\s+(у меня\s+)?(стоит|есть|висит|осталось|запланировано)\b",
    r"\bпланы?\s+на\s+(сегодня|завтра|неделю)\b",
    r"\b(найди|найти|поиск)\s+задач",
    r"\bзадач(и|у|)\s+(на\s+)?(сегодня|завтра|эту неделю)\b",
    r"\bчто\s+надо\s+(сделать|успеть)\b",
]

_ACTION_PATTERNS = [
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
    for pattern in _QUERY_PATTERNS:
        if re.search(pattern, t):
            return Intent.QUERY_TASKS
    for pattern in _ACTION_PATTERNS:
        if re.search(pattern, t):
            return Intent.NOTION_ACTION
    return Intent.SAVE


def classify_query(text: str) -> QueryType:
    """Classify the type of task query."""
    t = text.lower()
    if re.search(r"\bпросрочен", t):
        return QueryType.OVERDUE
    if re.search(r"\bзавтра\b", t):
        return QueryType.TOMORROW
    if re.search(r"\bсегодня\b|\bсейчас\b|\bна\s+день\b", t):
        return QueryType.TODAY
    if re.search(r"\b(в\s+процессе|in\s+progress|активн|незакрыт|не\s+сделан)\b", t):
        return QueryType.IN_PROGRESS
    return QueryType.ALL


# ── Task name extraction ────────────────────────────────────────────────────

_TRIGGER_PREFIX = re.compile(
    r"^(добавь|создай|запиши|поставь|внеси)\s+(задачу|задание|напоминание)[,;:\s]*",
    re.IGNORECASE,
)
_TASK_PREFIX = re.compile(r"^задач[уа][,;:\s]*", re.IGNORECASE)


def extract_task_name(text: str) -> str:
    """Strip intent trigger words and return the task name."""
    t = text.strip()
    t = _TRIGGER_PREFIX.sub("", t)
    t = _TASK_PREFIX.sub("", t)
    return t.strip()


# ── Project extraction ──────────────────────────────────────────────────────

_KNOWN_PROJECTS: dict[str, list[str]] = {
    "Контент-завод": ["контент-завод", "контент завод"],
    "Видео": ["видео"],
    "Маркетинговые материалы": ["маркетинговые материалы"],
    "Стратегия": ["стратегия", "стратегию"],
    "Лидогенерация": ["лидогенерация", "лидогенерацию"],
    "Мероприятия": ["мероприятия", "мероприятие"],
    "Организации и ассоциации": ["организации и ассоциации", "организации", "ассоциации"],
}

_EXPLICIT_PROJECT_RE = re.compile(r"^в\s+проект[еу]?\s+", re.IGNORECASE)
_IMPLICIT_IN_RE = re.compile(r"^в\s+", re.IGNORECASE)
_SEP_RE = re.compile(r"^[\s:—\-–,]+")


def _match_known_project(text: str) -> tuple[str | None, int]:
    """Match a known project at the start of *text*. Returns (canonical, length)."""
    low = text.lower()
    best: tuple[str | None, int] = (None, 0)
    for canonical, aliases in _KNOWN_PROJECTS.items():
        for alias in aliases:
            if low.startswith(alias) and len(alias) > best[1]:
                end = len(alias)
                # word boundary: next char must not be a letter
                if end >= len(low) or not low[end].isalpha():
                    best = (canonical, end)
    return best


def extract_project(text: str) -> tuple[str | None, str]:
    """Extract project from task text.

    Returns (project_name | None, cleaned_task_text).
    Patterns:
      - "в проект(е) X ..." → project X (known or unknown)
      - "в <known_project> ..." → known project only
    """
    t = text.strip()

    # 1. Explicit: "в проект(е) X ..."
    m = _EXPLICIT_PROJECT_RE.match(t)
    if m:
        after = t[m.end():]
        proj, length = _match_known_project(after)
        if proj:
            rest = _SEP_RE.sub("", after[length:], count=1).strip()
            return (proj, rest) if rest else (None, t)
        # Unknown project — take first word
        parts = re.split(r"[\s:—\-–]+", after, maxsplit=1)
        if parts[0]:
            rest = parts[1].strip() if len(parts) > 1 else ""
            return (parts[0].strip(), rest) if rest else (None, t)

    # 2. Implicit: "в <known_project> ..."
    m2 = _IMPLICIT_IN_RE.match(t)
    if m2:
        after = t[m2.end():]
        proj, length = _match_known_project(after)
        if proj:
            rest = _SEP_RE.sub("", after[length:], count=1).strip()
            return (proj, rest) if rest else (None, t)

    return None, t


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
