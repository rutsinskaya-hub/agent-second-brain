"""Трекер ежедневных ритуалов.

Почему отдельно от Notion: привычку нельзя выразить задачей. У задачи состояние
«сделано» — один раз и навсегда, у привычки «сделано сегодня», и завтра оно
сбрасывается. В Notion у ритуалов поле Status с Not started / Done, поэтому
отметить их там означало бы закрыть навсегда. Notion остаётся витриной списка
(блок «Ежедневно» в брифинге), отметки живут здесь.

Хранилище — vault/habits.json, тем же способом, что reminders.json и topics.json.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MOSCOW_TZ = timezone(timedelta(hours=3))

# Ядро — считаем серии и подсвечиваем в брифинге. Фон — просто отметка.
# auto: юзернейм публичного канала, по которому отметку можно поставить самим
# через t.me/s/. Telethon не используем: он уже блокировал Дарье телеграм.
HABITS: list[dict[str, Any]] = [
    {"key": "public",    "title": "Одно публичное действие",       "core": True,  "auto": None},
    {"key": "pressfeed", "title": "Pressfeed и комментарийка",     "core": True,  "auto": None},
    {"key": "lekarstva", "title": "Принять лекарства",             "core": True,  "auto": None},
    {"key": "ln",        "title": "Ленивая нейросеть",             "core": True,  "auto": "lenivaya_neiroset"},
    {"key": "nd",        "title": "Нейродевичник",                 "core": False, "auto": "aidevichnik"},
    {"key": "linkedin",  "title": "LinkedIn",                      "core": False, "auto": None},
    {"key": "anko",      "title": "Соцсети АНКО",                  "core": False, "auto": None},
    {"key": "avito",     "title": "Авито: заявки и чаты",          "core": False, "auto": None},
    {"key": "news",      "title": "Ньюсджекинг",                   "core": False, "auto": None},
    {"key": "tutorial",  "title": "Один туториал",                 "core": False, "auto": None},
    {"key": "telegram",  "title": "Прочитать Telegram",            "core": False, "auto": None},
]

BY_KEY = {h["key"]: h for h in HABITS}


def today_msk() -> date:
    """Сегодня по Москве — бот живёт на европейском VPS, дата по UTC уехала бы."""
    return datetime.now(MOSCOW_TZ).date()


class HabitStore:
    """Отметки ритуалов по дням: {'2026-08-30': {'ln': {...}}}."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._data: dict[str, dict[str, Any]] = {}
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self._data = {}
            return
        try:
            self._data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as e:
            # Битый файл не должен ронять вечернее сообщение: начинаем с чистого,
            # старое сохраняем рядом, чтобы история не пропала.
            logger.warning("habits.json не читается (%s), начинаю с пустого", e)
            try:
                self.path.rename(self.path.with_suffix(".json.broken"))
            except Exception:
                pass
            self._data = {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)  # атомарно: вечерний скрипт и бот пишут в один файл

    def day(self, day: date | None = None) -> dict[str, Any]:
        return self._data.get((day or today_msk()).isoformat(), {})

    def is_done(self, key: str, day: date | None = None) -> bool:
        return bool(self.day(day).get(key, {}).get("done"))

    def mark(self, key: str, done: bool, src: str = "manual", day: date | None = None) -> None:
        d = (day or today_msk()).isoformat()
        self._data.setdefault(d, {})[key] = {
            "done": done,
            "at": datetime.now(MOSCOW_TZ).strftime("%H:%M"),
            "src": src,
        }
        self.save()

    def toggle(self, key: str, day: date | None = None) -> bool:
        new = not self.is_done(key, day)
        self.mark(key, new, src="manual", day=day)
        return new

    def streak(self, key: str, day: date | None = None) -> int:
        """Сколько дней подряд отмечено.

        Незакрытый сегодняшний день серию не рвёт — иначе до вечера
        она показывала бы ноль каждый день.
        """
        cur = day or today_msk()
        if not self.is_done(key, cur):
            cur -= timedelta(days=1)
        n = 0
        while self.is_done(key, cur):
            n += 1
            cur -= timedelta(days=1)
        return n

    def done_count(self, day: date | None = None) -> int:
        return sum(1 for h in HABITS if self.is_done(h["key"], day))


def render_checklist(store: HabitStore, day: date | None = None) -> tuple[str, list[list[dict[str, str]]]]:
    """Текст и раскладка кнопок. Кнопки — сырые dict, без aiogram:
    этим же пользуется вечерний скрипт, который шлёт через Bot API напрямую.
    """
    d = day or today_msk()
    done = store.done_count(d)
    lines = [f"🔁 <b>Ритуалы {d.strftime('%d.%m')}</b> — {done} из {len(HABITS)}"]

    core = [h for h in HABITS if h["core"]]
    rest = [h for h in HABITS if not h["core"]]

    lines.append("\n<b>Ядро:</b>")
    for h in core:
        mark = "✅" if store.is_done(h["key"], d) else "⬜"
        s = store.streak(h["key"], d)
        tail = f" — {s} дн. подряд" if s else ""
        lines.append(f"{mark} {h['title']}{tail}")

    lines.append("\n<b>Фон:</b>")
    for h in rest:
        mark = "✅" if store.is_done(h["key"], d) else "⬜"
        lines.append(f"{mark} {h['title']}")

    rows: list[list[dict[str, str]]] = []
    row: list[dict[str, str]] = []
    for h in HABITS:
        mark = "✅" if store.is_done(h["key"], d) else "⬜"
        row.append({"text": f"{mark} {h['title']}", "callback_data": f"hab:{h['key']}"})
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    return "\n".join(lines), rows


def streaks_line(store: HabitStore, day: date | None = None) -> str:
    """Строка серий для утреннего брифинга. Пусто, если серий нет."""
    parts = []
    for h in HABITS:
        if not h["core"]:
            continue
        s = store.streak(h["key"], day)
        if s:
            parts.append(f"{h['title']} — {s}")
    return " · ".join(parts)
