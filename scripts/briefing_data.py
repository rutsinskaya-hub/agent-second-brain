#!/usr/bin/env python3
"""Утренний брифинг d-brain — формирует ГОТОВЫЙ Telegram-HTML детерминированно (без Claude).

Печатает в stdout итоговое сообщение. Календарь/Gmail сейчас отключены — блоки
показываются только при наличии данных.
"""
import asyncio
import os
import sys
from datetime import date

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # для report_fmt

from report_fmt import esc, clean_name, fmt_due, task_html  # noqa: E402


async def fetch_tasks() -> dict:
    from d_brain.services.notion import NotionClient

    token = os.environ.get("NOTION_TOKEN", "")
    if not token:
        return {}
    c = NotionClient(token)
    return {
        "overdue": await c.query_tasks("overdue", limit=20),
        "today": await c.query_tasks("today", limit=30),
        "daily": await c.query_tasks("daily", limit=15),
    }


async def main() -> None:
    today = date.today().strftime("%d.%m.%Y")
    try:
        d = await fetch_tasks()
    except Exception as e:
        print(f"Notion error: {e}", file=sys.stderr)
        d = {}

    overdue = d.get("overdue", [])
    today_tasks = d.get("today", [])
    daily = d.get("daily", [])

    P = [f"🌅 <b>Доброе утро! {today}</b>"]

    if overdue:
        P.append(f"\n🔴 <b>Просрочено ({len(overdue)}):</b>")
        for t in overdue:
            P.append(f"• {task_html(t['name'])} <i>— до {fmt_due(t.get('due_date', ''))}</i>")

    if today_tasks:
        P.append(f"\n✅ <b>На сегодня ({len(today_tasks)}):</b>")
        for t in today_tasks:
            P.append(f"• {task_html(t['name'])}")

    if daily:
        P.append("\n🔁 <b>Ежедневно:</b>")
        for t in daily:
            P.append(f"• {esc(clean_name(t['name']))}")

    if not (overdue or today_tasks):
        P.append("\nЗадач на сегодня нет — можно выдохнуть 🎉")

    print("\n".join(P))


if __name__ == "__main__":
    asyncio.run(main())
