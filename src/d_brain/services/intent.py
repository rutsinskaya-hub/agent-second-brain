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
    COMPLETE_TASK = "complete_task"  # Fast: mark Done via Notion API directly
    NOTION_ACTION = "notion_action"  # Slow: update/write via Claude + MCP
    CHECK_EMAIL = "check_email"    # Fetch & analyze Gmail
    MANAGE_EMAIL = "manage_email"  # Delete/trash emails
    CHECK_CALENDAR = "check_calendar"  # Show upcoming events
    CREATE_EVENT = "create_event"      # Add event to Google Calendar
    SET_REMINDER = "set_reminder"      # Set a timed reminder
    SAVE = "save"


class QueryType(Enum):
    OVERDUE = "overdue"
    TODAY = "today"
    TOMORROW = "tomorrow"
    IN_PROGRESS = "in_progress"
    ALL = "all"


# ── Intent patterns ────────────────────────────────────────────────────────

# "задачу" Deepgram иногда слышит как "за удачу" / "за дачу"
_TASK_NOUN = r"(?:задач\w*|за\s+[у]?дач\w*|задани\w*|напоминани\w*)"

_CREATE_PATTERNS = [
    r"\b(добав|созда|запиш|запис|постав|внес|завед|оформ|зафиксир|запланир|накид)\w*\s+" + _TASK_NOUN,
    r"\b(?:задач[уа]|за\s+[у]?дач[уа]|таск\w*)[,;:\s]\s*\S",
    r"\bнапомни\w*\s+(мне\s+)?о\b",
    r"\b(нов[аую]\w*|ещ[её]\s+однуа?)\s+задач",
]

_QUERY_PATTERNS = [
    r"\b(покажи|покажи?те|отобрази|выведи|список|дай|скинь|пришли|перечисли)\s+.{0,30}(задач|задани|дел[оаи]|спис|таск)",
    r"\bкакие\s+(у меня\s+)?(задач|задани|дела)\b",
    r"\bсколько\s+(у меня\s+)?.{0,15}задач",
    r"\bкогда\s+(дедлайн|срок)\b",
    r"\bчек-?лист\w*\b",
    r"\bчто\s+(по|с)\s+задач",
    r"\b(просроченн|незакрыт|активн|не\s*сделан)\w*.{0,20}задач",
    r"\bзадач\w*.{0,20}(просроченн|незакрыт|активн)\w*",
    r"\bкакие\s+(у\s+меня\s+)?.{0,20}задач",
    r"\bчто\s+(у меня\s+)?(стоит|есть|висит|осталось|запланировано)\b",
    r"\bпланы?\s+на\s+(сегодня|завтра|неделю)\b",
    r"\b(найди|найти|поиск)\s+задач",
    r"\bзадач(и|у|)\s+(на\s+)?(сегодня|завтра|эту неделю)\b",
    r"\bчто\s+надо\s+(сделать|успеть)\b",
    r"\bзадач\w*\s+(в\s+|по\s+)\w",             # "задачи в стратегии", "задачи по проекту"
    r"\bчто\s+(в|по)\s+проект",                  # "что в проекте X", "что по проекту X"
    r"\bчто\s+в\s+\w+\b.{0,10}$",               # "что в мероприятиях" (короткая фраза)
]

# Mark done — verb stems cover imperative/infinitive/synonyms.
# Handled by the fast direct-API path (COMPLETE_TASK), not Claude+MCP.
_COMPLETE_PATTERNS = [
    r"\b(отмет\w*|помет\w*|закр\w*|заверш\w*|выполн\w*|законч\w*|поставь)\s+.{0,40}(выполнен|готов|сделан|закрыт|done)",
    r"\b(закр\w*|заверш\w*|выполн\w*|законч\w*)\s+.{0,40}(задач|таск)",
    r"\b(выполнил[аи]?|сделал[аи]?|закрыл[аи]?|законч\w*)\s+(задачу|это|её|таск\w*)\b",
    r"\bзадач[уа]\s+.{0,40}\s*(выполнен|готов|сделан|закрыт)",
    r"\bзадача\s+.{0,40}\s+(выполнена|готова|сделана|закрыта)\b",
    r"\b(галочк\w*|чекбокс)\s+.{0,30}задач",
]

# Update deadline — still delegated to Claude+MCP (NOTION_ACTION).
# Verb stems so infinitive/imperative both hit
# ("перенеси"/"перенести"/"перенесите", "сдвинь"/"сдвинуть", "отложи", ...)
_ACTION_PATTERNS = [
    r"\b(перенес\w*|передвин\w*|сдвин\w*|отлож\w*|перекин\w*)\s+.{0,60}\bна\s+",
    r"\b(измен\w*|обнов\w*|сдвин\w*|поменя\w*|поставь)\s+.{0,20}(дедлайн|срок|дат\w*)\b",
    r"\b(дедлайн|срок)\s+.{0,30}(перенес\w*|передвин\w*|сдвин\w*|измен\w*|поменя\w*)",
]

_MANAGE_EMAIL_PATTERNS = [
    r"\b(удали|удалить|убери|убрать|очисти|очистить|сотри|стереть|выброси|выбросить)\s+.{0,40}(письм|почт|mail|email|рассылк)",
    r"\b(письм|почт|рассылк)\w*\s+.{0,30}(удали|убери|очисти|сотри|выброси)",
    r"\b(удали|убери|очисти)\s+(все|всё)\s+(от|из)\b",
    r"\b(отпиши|отписать|отписаться)\s+от\b",
]

_REMINDER_PATTERNS = [
    r"\bнапомн\w*\b",             # напомни / напомнить / напоминай
    r"\b(напоминани[ея]|напоминалк[уа])\s+(на|в|через)\b",
    r"\b(поставь|установи|сделай)\s+напоминани",
    r"\bне\s+забуд\w*\b",         # «не забудь ...»
    r"\bпни\s+меня\b",
    r"\bremind\w*\b",
]

_CREATE_EVENT_PATTERNS = [
    r"\b(добав|созда|запиш|запис|постав|назначь|поставь|запланируй)\w*\s+.{0,20}(встреч|совещани|созвон|событи|мероприяти|мит(?:инг)?|звонок|колл)",
    r"\b(встреч[уа]|совещани[ея]|созвон|событи[ея]|мероприяти[ея]|мит(?:инг)?|звонок|колл)\s+.{0,30}(добав|созда|запиш|запис|назначь|запланируй)",
    r"\b(добав|созда|запланируй)\w*\s+в\s+календарь\b",
    r"\bв\s+календарь\s+(добав|созда|запиш|запланируй)",
]

_CALENDAR_PATTERNS = [
    r"\b(календарь|расписание|расписани[еяю])\b",
    r"\bчто\s+(у меня\s+)?(сегодня|завтра|на\s+неделе?)\s*(по\s+)?встреч",
    r"\b(встреч[иа]|совещани[еяю]|созвон[ыа]?|звонк[иа]|мит(?:инг)?)\s+(на\s+)?(сегодня|завтра)",
    r"\b(сегодня|завтра)\s+(какие\s+)?(встреч|совещани|созвон|мит(?:инг)?)",
    r"\bкакие\s+(у меня\s+)?(встреч|мит(?:инг)?|событи)",
    r"\bчто\s+в\s+календар",
    r"\bсобыти[яей]\s+(на\s+)?(сегодня|завтра|неделю)",
    r"\bcalendar\b",
]

_EMAIL_PATTERNS = [
    r"\bпроверь\s+(почту|почта|mail|email|имейл|мейл)",
    r"\b(что|чё|че)\s+(на\s+почте|в\s+почте|на\s+mail|в\s+mail)",
    r"\bновые?\s+письм[аое]",
    r"\bпочт[уа]\b",
    r"\bemail\b",
    r"\bписьм[аое]\b",
]


def classify(text: str) -> Intent:
    """Classify text intent. Returns Intent enum value."""
    t = text.lower()
    for pattern in _REMINDER_PATTERNS:
        if re.search(pattern, t):
            return Intent.SET_REMINDER
    # Mark-done / update actions must win over CREATE: the create patterns are
    # greedy ("задачу <word>" matches any sentence mentioning a task), so an
    # action like "пометь сделанным задачу X" would otherwise be misread as new.
    for pattern in _COMPLETE_PATTERNS:
        if re.search(pattern, t):
            return Intent.COMPLETE_TASK
    for pattern in _ACTION_PATTERNS:
        if re.search(pattern, t):
            return Intent.NOTION_ACTION
    for pattern in _CREATE_PATTERNS:
        if re.search(pattern, t):
            return Intent.CREATE_TASK
    for pattern in _QUERY_PATTERNS:
        if re.search(pattern, t):
            return Intent.QUERY_TASKS
    for pattern in _MANAGE_EMAIL_PATTERNS:
        if re.search(pattern, t):
            return Intent.MANAGE_EMAIL
    for pattern in _CREATE_EVENT_PATTERNS:
        if re.search(pattern, t):
            return Intent.CREATE_EVENT
    for pattern in _CALENDAR_PATTERNS:
        if re.search(pattern, t):
            return Intent.CHECK_CALENDAR
    for pattern in _EMAIL_PATTERNS:
        if re.search(pattern, t):
            return Intent.CHECK_EMAIL
    return Intent.SAVE


# ── Command smell: does an unclassified message look like a command? ──────────
# Used to decide whether to fall back to the LLM. If a message reaches SAVE but
# smells like a command (a task/reminder noun, an action verb stem, or a date
# next to a verb), we hand it to Claude instead of silently saving. Plain notes
# ("купить молоко", "мысль на подумать") have no smell and stay instant + free.
_SMELL_NOUNS = re.compile(
    r"\b(задач\w*|таск\w*|дедлайн\w*|срок\w*|напоминани\w*|дел[оаи]\b)", re.I)
_SMELL_VERBS = re.compile(
    r"\b(добав\w*|созда\w*|завед\w*|оформ\w*|запиш\w*|запис\w*|внес\w*|постав\w*|"
    r"запланир\w*|зафиксир\w*|отмет\w*|помет\w*|закр\w*|заверш\w*|выполн\w*|"
    r"законч\w*|сдела\w*|перенес\w*|передвин\w*|сдвин\w*|отлож\w*|перекин\w*|"
    r"перекинь|измен\w*|обнов\w*|поменя\w*|удал\w*|убер\w*|покажи\w*|выведи\w*|"
    r"перечисл\w*|напомн\w*|пни|скинь|пришли|дай|найди|провер\w*|отправ\w*)", re.I)
_SMELL_DATE = re.compile(
    r"\b(сегодня|завтра|послезавтра|понедельник|вторник|сред[уа]|четверг|"
    r"пятниц[уа]|суббот[уа]|воскресень[еи]|\d{1,2}[./]\d{1,2}|\d{1,2}\s*"
    r"(январ|феврал|март|апрел|ма[йя]|июн|июл|август|сентябр|октябр|ноябр|декабр))",
    re.I)


def has_command_smell(text: str) -> bool:
    """True if an unclassified message plausibly is a command, not a note."""
    t = text.lower()
    if _SMELL_NOUNS.search(t):
        return True
    if _SMELL_VERBS.search(t):
        return True
    # a date alone isn't enough, but a date next to any verb-ish word is
    if _SMELL_DATE.search(t) and re.search(r"\b\w+(ть|ти|и|й|нь)\b", t):
        return True
    return False


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
    r"^(добав|созда|запиш|запис|постав|внес)\w*\s+" + _TASK_NOUN + r"[,;:\s]*",
    re.IGNORECASE,
)
_TASK_PREFIX = re.compile(r"^(?:задач[уаие]?|за\s+[у]?дач[уаие]?)[,;:\s]*", re.IGNORECASE)


def extract_task_name(text: str) -> str:
    """Strip intent trigger words and return the task name."""
    t = text.strip()
    t = _TRIGGER_PREFIX.sub("", t)
    t = _TASK_PREFIX.sub("", t)
    return t.strip()


# Command words to drop from a "mark done" phrase, leaving only the words that
# identify *which* task. The leftover is fuzzy-matched against real task titles,
# so this need not be exhaustive — just remove the obvious command noise.
_COMPLETE_STRIP = re.compile(
    r"\b("
    r"помет\w*|отмет\w*|закр\w*|заверш\w*|выполн\w*|законч\w*|сделал[аи]?|"
    r"поставь|галочк\w*|чекбокс|"
    r"задач[уаеи]?|таск\w*|это|её|ее|как|"
    r"готов\w*|сделан\w*|закрыт\w*|done"
    r")\b",
    re.IGNORECASE,
)


def extract_completion_query(text: str) -> str:
    """Strip 'mark done' command words, leaving the task identifier phrase."""
    t = _COMPLETE_STRIP.sub(" ", text.lower())
    return re.sub(r"\s+", " ", t).strip()


# ── Project extraction ──────────────────────────────────────────────────────

_KNOWN_PROJECTS: dict[str, list[str]] = {
    "Контент-завод тексты": ["контент-завод тексты", "контент завод тексты", "контент-завод текст", "контент-завод", "контент завод", "контент-заводе", "контент заводе"],
    "Контент-завод видео": ["контент-завод видео", "контент завод видео", "видео"],
    "Маркетинговые материалы": ["маркетинговые материалы", "маркетинговых материалах", "маркетинговых материалов"],
    "Стратегия": ["стратегия", "стратегию", "стратегии"],
    "Лидогенерация": ["лидогенерация", "лидогенерацию", "лидогенерации"],
    "Мероприятия": ["мероприятия", "мероприятие", "мероприятиях"],
    "Организации и ассоциации": ["организации и ассоциации", "организациях и ассоциациях", "организации", "ассоциации", "организациях", "ассоциациях"],
    "Zapusk International": ["запуск international", "zapusk international", "запуск интернешнл", "запуск интернэшнл", "запуск интернешнел", "запуск интернешенал", "запуск интернационал", "запуск интернешнал"],
    "Социальные сети": ["социальные сети", "социальных сетях", "социальных сетей", "соцсети", "соцсетях"],
    "СМИ": ["сми"],
    "Встречи и совещания": ["встречи и совещания", "встречах и совещаниях", "встречи", "совещания", "встречах", "совещаниях"],
    "Hubspot+Skillbox": ["hubspot+skillbox", "hubspot skillbox", "хабспот", "хабспот скилбокс"],
    "Запуск Энергосбыт": ["запуск энергосбыт", "энергосбыт", "энергосбыте"],
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


_QUERY_PROJECT_RE = re.compile(
    r"(?:в\s+проект\w*|по\s+проект\w*)\s+",
    re.IGNORECASE,
)


def extract_query_project(text: str) -> str | None:
    """Find a project name mentioned anywhere in query text."""
    t = text.lower()

    # 1. Explicit: "в проекте X", "по проекту X"
    m = _QUERY_PROJECT_RE.search(t)
    if m:
        after = t[m.end():]
        proj, _ = _match_known_project(after)
        if proj:
            return proj
        word = re.split(r"[\s,;:]+", after, maxsplit=1)[0].strip()
        if word:
            return word

    # 2. Any known project name anywhere in text
    best: tuple[str | None, int] = (None, 0)
    for canonical, aliases in _KNOWN_PROJECTS.items():
        for alias in aliases:
            idx = t.find(alias)
            if idx >= 0 and len(alias) > best[1]:
                end = idx + len(alias)
                if end >= len(t) or not t[end].isalpha():
                    if idx == 0 or not t[idx - 1].isalpha():
                        best = (canonical, len(alias))
    return best[0]


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
