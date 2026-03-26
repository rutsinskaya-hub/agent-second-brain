#!/usr/bin/env python3
"""Collect all briefing data: Calendar + Gmail + Notion tasks.

Outputs structured text to stdout for injection into Claude prompt.
"""

import asyncio
import os
import sys
from datetime import date, timedelta, timezone

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "src"))

MOSCOW_TZ = timezone(timedelta(hours=3))


def fetch_calendar() -> str:
    """Fetch today's calendar events."""
    try:
        from d_brain.services.calendar import CalendarClient

        creds = os.path.join(PROJECT_DIR, "gcp-oauth.keys.json")
        token = os.path.join(PROJECT_DIR, "calendar-token.json")
        client = CalendarClient(creds, token)

        if not client.enabled:
            return ""

        events = client.fetch_all_calendars_events(days=1, max_results=20)
        return client.format_for_briefing(events)
    except Exception as e:
        print(f"Calendar error: {e}", file=sys.stderr)
        return ""


def fetch_gmail() -> str:
    """Fetch unread emails."""
    try:
        from d_brain.services.gmail import GmailClient

        creds = os.path.join(PROJECT_DIR, "gcp-oauth.keys.json")
        token = os.path.join(PROJECT_DIR, "gmail-token.json")
        client = GmailClient(creds, token)

        if not client.enabled:
            return ""

        emails = client.fetch_emails(hours=24, unread_only=True, max_results=15)
        if emails:
            return client.format_for_claude(emails)
        return "Новых писем нет."
    except Exception as e:
        print(f"Gmail error: {e}", file=sys.stderr)
        return ""


async def fetch_tasks() -> str:
    """Fetch tasks from Notion: overdue + today + in progress."""
    try:
        from d_brain.services.notion import NotionClient

        token = os.environ.get("NOTION_TOKEN", "")
        if not token:
            return ""

        client = NotionClient(token)
        today = date.today().isoformat()

        overdue = await client.query_tasks("overdue", limit=10)
        today_tasks = await client.query_tasks("today", limit=10)
        in_progress = await client.query_tasks("in_progress", limit=10)

        lines = [f"=== ЗАДАЧИ (Notion) ===\n"]

        if overdue:
            lines.append("ПРОСРОЧЕНО:")
            for t in overdue:
                due = t.get("due_date", "")
                lines.append(f"- {t['name']} (срок: {due})")
            lines.append("")

        if today_tasks:
            lines.append(f"НА СЕГОДНЯ ({today}):")
            for t in today_tasks:
                lines.append(f"- {t['name']} [{t.get('status', '')}]")
            lines.append("")

        if in_progress:
            lines.append("В РАБОТЕ:")
            for t in in_progress:
                due = t.get("due_date", "")
                due_str = f" (срок: {due})" if due else ""
                lines.append(f"- {t['name']}{due_str}")
            lines.append("")

        if not overdue and not today_tasks and not in_progress:
            # Fallback: show not started
            not_started = await client.query_tasks("all", limit=5)
            if not_started:
                lines.append("БЛИЖАЙШИЕ ЗАДАЧИ:")
                for t in not_started[:5]:
                    due = t.get("due_date", "")
                    due_str = f" (срок: {due})" if due else ""
                    lines.append(f"- {t['name']}{due_str}")
                lines.append("")

        lines.append("=== КОНЕЦ ЗАДАЧ ===")
        return "\n".join(lines)
    except Exception as e:
        print(f"Notion error: {e}", file=sys.stderr)
        return ""


async def main() -> None:
    # Run calendar and gmail sync, tasks async
    calendar_data = fetch_calendar()
    gmail_data = fetch_gmail()
    tasks_data = await fetch_tasks()

    sections = []
    if calendar_data:
        sections.append(calendar_data)
    if tasks_data:
        sections.append(tasks_data)
    if gmail_data:
        sections.append(gmail_data)

    print("\n\n".join(sections))


if __name__ == "__main__":
    asyncio.run(main())
