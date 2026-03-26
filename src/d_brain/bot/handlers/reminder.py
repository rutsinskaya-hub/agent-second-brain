"""Reminder handler — set and list reminders."""

import logging
from datetime import datetime, timedelta, timezone

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from d_brain.bot.utils import run_with_progress
from d_brain.config import Settings
from d_brain.services.processor import ClaudeProcessor
from d_brain.services.reminders import MOSCOW_TZ, ReminderScheduler

router = Router(name="reminder")
logger = logging.getLogger(__name__)

# Global scheduler instance — set from main.py
scheduler: ReminderScheduler | None = None


def _parse_response(text: str) -> dict[str, str]:
    """Parse Claude's REMINDER_* response."""
    result: dict[str, str] = {}
    for line in text.split("\n"):
        line = line.strip()
        for key in ("REMINDER_TEXT", "REMINDER_DATE", "REMINDER_TIME"):
            if line.upper().startswith(key + ":"):
                result[key] = line[len(key) + 1:].strip()
                break
    return result


@router.message(Command("reminders"))
async def cmd_reminders(message: Message) -> None:
    """Show active reminders."""
    if not scheduler:
        await message.answer("⏰ Напоминания не настроены.")
        return

    chat_id = message.chat.id
    active = scheduler.list_active(chat_id)

    if not active:
        await message.answer("⏰ Активных напоминаний нет.")
        return

    lines = [f"⏰ <b>Напоминания ({len(active)})</b>\n"]
    for r in active:
        time_str = r.fire_at.strftime("%d.%m %H:%M")
        lines.append(f"• <b>{time_str}</b> — {r.text}")
    await message.answer("\n".join(lines))


async def set_reminder_intent(
    message: Message, settings: Settings, user_text: str
) -> None:
    """Handle reminder creation from voice/text."""
    if not scheduler:
        await message.answer("⏰ Напоминания не настроены.")
        return

    status_msg = await message.answer("⏰ Создаю напоминание...")

    processor = ClaudeProcessor(settings.vault_path, settings.notion_token)

    result = await run_with_progress(
        status_msg,
        "Анализирую...",
        lambda: processor.parse_reminder(user_text),
    )

    if "error" in result:
        await status_msg.edit_text(f"❌ {result['error']}")
        return

    report = result.get("report", "")
    parsed = _parse_response(report)

    reminder_text = parsed.get("REMINDER_TEXT", "").strip()
    date_str = parsed.get("REMINDER_DATE", "").strip()
    time_str = parsed.get("REMINDER_TIME", "").strip()

    if not reminder_text or not date_str or not time_str:
        await status_msg.edit_text(
            f"❌ Не удалось разобрать напоминание:\n<code>{report[:500]}</code>"
        )
        return

    try:
        fire_at = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        fire_at = fire_at.replace(tzinfo=MOSCOW_TZ)
    except ValueError as e:
        await status_msg.edit_text(f"❌ Ошибка разбора времени: {e}")
        return

    now = datetime.now(MOSCOW_TZ)
    if fire_at <= now:
        await status_msg.edit_text("❌ Время напоминания уже прошло.")
        return

    reminder = scheduler.add(
        chat_id=message.chat.id,
        text=reminder_text,
        fire_at=fire_at,
    )

    delta = fire_at - now
    if delta.total_seconds() < 3600:
        when = f"через {int(delta.total_seconds() / 60)} мин"
    elif delta.total_seconds() < 86400:
        hours = int(delta.total_seconds() / 3600)
        mins = int((delta.total_seconds() % 3600) / 60)
        when = f"через {hours}ч {mins}мин" if mins else f"через {hours}ч"
    else:
        when = fire_at.strftime("%d.%m в %H:%M")

    await status_msg.edit_text(
        f"✅ <b>Напоминание установлено</b>\n\n"
        f"⏰ {fire_at.strftime('%d.%m.%Y %H:%M')} ({when})\n"
        f"📝 {reminder_text}"
    )
    logger.info("Reminder set: %s at %s — %s", reminder.id, fire_at, reminder_text[:40])
