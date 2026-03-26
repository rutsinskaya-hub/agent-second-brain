"""Calendar handler — show Google Calendar events."""

import logging
import re

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from d_brain.config import Settings
from d_brain.services.calendar import CalendarClient

router = Router(name="calendar")
logger = logging.getLogger(__name__)


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
