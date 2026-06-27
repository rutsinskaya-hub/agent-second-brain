#!/usr/bin/env python3
"""Вечерний итог d-brain — формирует ГОТОВЫЙ Telegram-HTML детерминированно (без Claude).

Печатает в stdout итоговое сообщение: просрочка + завтрашние задачи + завтрашний
календарь (если включён) + активные напоминания.
"""
import asyncio
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # для report_fmt

from report_fmt import esc, clean_name, fmt_due  # noqa: E402

MOSCOW_TZ = timezone(timedelta(hours=3))


def fetch_reminders() -> list:
    try:
        p = os.path.join(PROJECT_DIR, "vault", "reminders.json")
        if not os.path.exists(p):
            return []
        data = json.loads(open(p).read())
        now = datetime.now(MOSCOW_TZ)
        active = [r for r in data if datetime.fromisoformat(r["fire_at"]) > now]
        active.sort(key=lambda r: r["fire_at"])
        return [(datetime.fromisoformat(r["fire_at"]).strftime("%d.%m %H:%M"), r["text"]) for r in active]
    except Exception as e:
        print(f"Reminders error: {e}", file=sys.stderr)
        return []


def fetch_calendar_tomorrow() -> list:
    try:
        from d_brain.services.calendar import CalendarClient

        creds = os.path.join(PROJECT_DIR, "gcp-oauth.keys.json")
        token = os.path.join(PROJECT_DIR, "calendar-token.json")
        client = CalendarClient(creds, token)
        if not client.enabled:
            return []
        events = client.fetch_events(days=2, max_results=20)
        tomorrow = (datetime.now(MOSCOW_TZ) + timedelta(days=1)).date()
        out = []
        for ev in events:
            try:
                ev_date = datetime.fromisoformat(ev.get("start_sort", "")).date()
            except (ValueError, TypeError):
                ev_date = tomorrow
            if ev_date == tomorrow:
                tm = "весь день" if ev["all_day"] else ev["start"]
                out.append((tm, ev["summary"]))
        return out
    except Exception as e:
        print(f"Calendar error: {e}", file=sys.stderr)
        return []


async def fetch_tasks() -> tuple:
    from d_brain.services.notion import NotionClient

    token = os.environ.get("NOTION_TOKEN", "")
    if not token:
        return [], []
    c = NotionClient(token)
    overdue = await c.query_tasks("overdue", limit=20)
    tomorrow = await c.query_tasks("tomorrow", limit=20)
    return overdue, tomorrow


async def main() -> None:
    today = date.today().strftime("%d.%m.%Y")
    try:
        overdue, tomorrow = await fetch_tasks()
    except Exception as e:
        print(f"Notion error: {e}", file=sys.stderr)
        overdue, tomorrow = [], []
    cal = fetch_calendar_tomorrow()
    rem = fetch_reminders()

    P = [f"🌙 <b>Итог дня: {today}</b>"]

    if overdue:
        P.append(f"\n🔴 <b>Просрочено ({len(overdue)}):</b>")
        for t in overdue:
            P.append(f"• {esc(clean_name(t['name']))} <i>— до {fmt_due(t.get('due_date', ''))}</i>")

    if cal:
        P.append("\n📅 <b>Завтра в календаре:</b>")
        for tm, s in cal:
            P.append(f"• {esc(tm)} — {esc(s)}")

    if tomorrow:
        P.append(f"\n📝 <b>Задачи на завтра ({len(tomorrow)}):</b>")
        for t in tomorrow:
            P.append(f"• {esc(clean_name(t['name']))}")

    if rem:
        P.append("\n⏰ <b>Напоминания:</b>")
        for tm, txt in rem:
            P.append(f"• {esc(tm)} — {esc(txt)}")

    if not (overdue or tomorrow or rem or cal):
        P.append("\nНа завтра пусто — день закрыт 🎉")

    print("\n".join(P))


if __name__ == "__main__":
    asyncio.run(main())
