"""Автоотметка ритуалов, которые видно снаружи.

Читаем публичную веб-витрину канала t.me/s/<username> — без Telethon и без
логина. Telethon здесь принципиально не используется: он уже приводил к
блокировке телеграма Дарьи, безопасный контур = Bot API плюс t.me/s/.

Автоматически закрываем только то, что реально проверяемо: был ли сегодня пост
в канале. «Посмотреть туториал» или «принять лекарства» снаружи не видно —
такие ритуалы остаются ручными, и это осознанно.
"""

from __future__ import annotations

import logging
import re
import urllib.error
import urllib.request
from datetime import date, datetime

from d_brain.services.habits import HABITS, MOSCOW_TZ, HabitStore, today_msk

logger = logging.getLogger(__name__)

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
TIME_RE = re.compile(r'datetime="([0-9T:+\-\.]+)"')


def channel_posted_on(username: str, day: date | None = None, timeout: int = 15) -> bool | None:
    """Был ли пост в канале в указанный день по Москве.

    Возвращает None, если страницу не удалось прочитать — это важно отличать
    от «постов не было»: по None мы просто не трогаем ручную отметку.
    """
    target = day or today_msk()
    url = f"https://t.me/s/{username.lstrip('@')}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            html = r.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        logger.warning("t.me/s/%s не читается: %s", username, e)
        return None

    for raw in TIME_RE.findall(html):
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            continue
        if dt.tzinfo is None:
            continue
        if dt.astimezone(MOSCOW_TZ).date() == target:
            return True
    return False


def run_autochecks(store: HabitStore, day: date | None = None) -> dict[str, bool]:
    """Проставляет автоотметки и возвращает {ключ: результат} по тем, что сработали.

    Ручную отметку не снимаем никогда: если Дарья отметила канал руками, а пост
    в витрине не виден (например, он в сторис или закреплён давно), её отметка
    важнее нашей проверки.
    """
    d = day or today_msk()
    out: dict[str, bool] = {}
    for h in HABITS:
        username = h.get("auto")
        if not username:
            continue
        posted = channel_posted_on(username, d)
        if posted is None:
            continue
        if posted and not store.is_done(h["key"], d):
            store.mark(h["key"], True, src="auto", day=d)
            out[h["key"]] = True
    return out
