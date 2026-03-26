"""Calendar handler — show and create Google Calendar events."""

import logging
import re
from datetime import datetime, timedelta

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from d_brain.bot.utils import run_with_progress
from d_brain.config import Settings
from d_brain.services.calendar import CalendarClient
from d_brain.services.processor import ClaudeProcessor

router = Router(name="calendar")
logger = logging.getLogger(__name__)

_MOSCOW_OFFSET = timedelta(hours=3)


def _parse_days(text: str) -> tuple[int, str]:
    """Parse how many days to show from user text. Returns (days, title)."""
    t = text.lower()
    if re.search(r"\bзавтра\b", t):
        return 2, "Сегодня и завтра"
    if re.search(r"\bнедел[юяе]\b", t):
        return 7, "На неделю"
    return 1, "Сегодня"


@router.message(Command("calendar"))
async def cmd_calendar(message: Message, settings: Settings) -> None:
    """Handle /calendar command."""
    text = message.text or ""
    args = text.replace("/calendar", "").strip()
    await check_calendar_intent(message, settings, args)


async def check_calendar_intent(
    message: Message, settings: Settings, user_text: str = ""
) -> None:
    """Shared logic for /calendar command, button, and voice/text intent."""
    if not settings.calendar_enabled:
        await message.answer(
            "📅 Календарь не настроен. Запусти OAuth:\n"
            "<code>python -m d_brain.services.calendar --setup</code>"
        )
        return

    days, title = _parse_days(user_text)

    client = CalendarClient(
        settings.gmail_credentials_path, settings.calendar_token_path
    )

    try:
        events = client.fetch_all_calendars_events(days=days, max_results=30)
    except Exception as e:
        logger.exception("Calendar fetch failed")
        await message.answer(f"❌ Ошибка Calendar: {e}")
        return

    reply = client.format_events_html(events, title=title)
    await message.answer(reply)
    logger.info("Calendar check: %d events for %d days", len(events), days)


def _parse_event_response(text: str) -> dict[str, str]:
    """Parse Claude's EVENT_* response into a dict."""
    result: dict[str, str] = {}
    for line in text.split("\n"):
        line = line.strip()
        for key in ("EVENT_SUMMARY", "EVENT_DATE", "EVENT_START", "EVENT_END", "EVENT_LOCATION"):
            if line.upper().startswith(key + ":"):
                val = line[len(key) + 1:].strip()
                result[key] = val
                break
    return result


async def create_event_intent(
    message: Message, settings: Settings, user_text: str
) -> None:
    """Handle calendar event creation from voice/text."""
    if not settings.calendar_enabled:
        await message.answer("📅 Календарь не настроен.")
        return

    status_msg = await message.answer("📅 Создаю событие...")

    processor = ClaudeProcessor(settings.vault_path, settings.notion_token)

    result = await run_with_progress(
        status_msg,
        "Анализирую...",
        lambda: processor.parse_calendar_event(user_text),
    )

    if "error" in result:
        await status_msg.edit_text(f"❌ {result['error']}")
        return

    report = result.get("report", "")
    parsed = _parse_event_response(report)

    summary = parsed.get("EVENT_SUMMARY", "").strip()
    date_str = parsed.get("EVENT_DATE", "").strip()
    start_str = parsed.get("EVENT_START", "").strip()
    end_str = parsed.get("EVENT_END", "").strip()
    location = parsed.get("EVENT_LOCATION", "").strip()

    if not summary or not date_str:
        await status_msg.edit_text(
            f"❌ Не удалось разобрать событие:\n<code>{report[:500]}</code>"
        )
        return

    all_day = start_str.upper() == "ALL_DAY"

    try:
        event_date = datetime.strptime(date_str, "%Y-%m-%d")

        if all_day:
            from datetime import timezone
            tz = timezone(_MOSCOW_OFFSET)
            start_dt = event_date.replace(tzinfo=tz)
            end_dt = start_dt + timedelta(days=1)
        else:
            from datetime import timezone
            tz = timezone(_MOSCOW_OFFSET)
            h, m = map(int, start_str.split(":"))
            start_dt = event_date.replace(hour=h, minute=m, tzinfo=tz)

            if end_str and ":" in end_str:
                eh, em = map(int, end_str.split(":"))
                end_dt = event_date.replace(hour=eh, minute=em, tzinfo=tz)
            else:
                end_dt = start_dt + timedelta(hours=1)
    except (ValueError, TypeError) as e:
        await status_msg.edit_text(f"❌ Ошибка разбора даты: {e}")
        return

    client = CalendarClient(
        settings.gmail_credentials_path, settings.calendar_token_path
    )

    try:
        created = client.create_event(
            summary=summary,
            start=start_dt,
            end=end_dt,
            location=location,
            all_day=all_day,
        )
    except Exception as e:
        logger.exception("Failed to create calendar event")
        await status_msg.edit_text(f"❌ Ошибка создания: {e}")
        return

    if all_day:
        time_info = "весь день"
    else:
        time_info = f"{start_dt.strftime('%H:%M')}–{end_dt.strftime('%H:%M')}"

    reply = (
        f"✅ <b>Событие создано</b>\n\n"
        f"📅 {event_date.strftime('%d.%m.%Y')} ({time_info})\n"
        f"📝 {summary}"
    )
    if location:
        reply += f"\n📍 {location}"

    await status_msg.edit_text(reply)
    logger.info("Calendar event created: %s on %s", summary, date_str)
