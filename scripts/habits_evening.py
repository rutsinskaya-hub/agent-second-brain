#!/usr/bin/env python3
"""Вечерний чеклист ритуалов: автоотметки + сообщение с кнопками.

Запускается из evening.sh после итога дня. Кнопки обрабатывает сам бот
(handlers/habits.py) — здесь только отправка.

Шлём напрямую через Bot API, а не через curl из shell: сообщению нужен
reply_markup с JSON-раскладкой кнопок, а собирать вложенный JSON в bash —
верный способ поймать проблему с кодировкой.
"""
import json
import logging
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR / "src"))

# Без этого предупреждения автопроверки («t.me/s/... не читается») уходят
# в никуда, и молчаливый пропуск отметки выглядит как её отсутствие.
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stderr)

from d_brain.services.habits import HabitStore, render_checklist  # noqa: E402


def send(token: str, chat_id: str, text: str, rows: list) -> dict:
    payload = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "reply_markup": json.dumps({"inline_keyboard": rows}, ensure_ascii=False),
    }).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def main() -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("ALLOWED_USER_IDS", "").strip("[] ").split(",")[0].strip()
    if not token or not chat_id:
        print("TELEGRAM_BOT_TOKEN или ALLOWED_USER_IDS не заданы", file=sys.stderr)
        return 1

    # VAULT_PATH в .env задан относительным («./vault»), поэтому разрешаем его
    # от корня проекта, а не от текущей директории: иначе запуск не из корня
    # завёл бы вторую, пустую историю отметок.
    vault = Path(os.environ.get("VAULT_PATH") or "vault")
    if not vault.is_absolute():
        vault = PROJECT_DIR / vault
    store = HabitStore(vault / "habits.json")

    # Автоотметки идут первыми, чтобы в сообщении уже стояли галочки по каналам.
    # Падение проверки не должно ронять чеклист — он полезен и без неё.
    try:
        from d_brain.services.habit_autocheck import run_autochecks

        auto = run_autochecks(store)
        if auto:
            print(f"автоотметки: {', '.join(auto)}", file=sys.stderr)
    except Exception as e:
        print(f"автопроверка не отработала: {e}", file=sys.stderr)

    text, rows = render_checklist(store)
    res = send(token, chat_id, text, rows)
    if not res.get("ok"):
        print(f"Telegram отказал: {res}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
