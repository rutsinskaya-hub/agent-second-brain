"""Handler for /task command — instant Notion task creation."""

import logging
import re
from datetime import date, timedelta

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from d_brain.bot.states import TaskCommandState
from d_brain.config import Settings
from d_brain.services.notion import NotionClient

router = Router(name="task")
logger = logging.getLogger(__name__)

# Patterns to detect date hints in task text
_TODAY_RE = re.compile(r"\bсегодня\b", re.IGNORECASE)
_TOMORROW_RE = re.compile(r"\bзавтра\b", re.IGNORECASE)
_DATE_RE = re.compile(r"\b(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?\b")


def _extract_due_date(text: str) -> str | None:
    """Try to detect a due date hint in the task text."""
    today = date.today()
    if _TODAY_RE.search(text):
        return today.isoformat()
    if _TOMORROW_RE.search(text):
        return (today + timedelta(days=1)).isoformat()
    m = _DATE_RE.search(text)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        year_raw = m.group(3)
        year = int(year_raw) if year_raw else today.year
        if year < 100:
            year += 2000
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            pass
    return None


@router.message(Command("task"))
async def cmd_task(
    message: Message, command: CommandObject, state: FSMContext, settings: Settings
) -> None:
    """Handle /task command. Usage: /task <task text>"""
    if command.args:
        await _create_task(message, command.args.strip(), settings)
        return

    await state.set_state(TaskCommandState.waiting_for_input)
    await message.answer(
        "📝 <b>Какую задачу добавить?</b>\n\n"
        "Напиши текст задачи. Можно указать дату: «завтра», «сегодня» или «15.03»."
    )


@router.message(TaskCommandState.waiting_for_input)
async def handle_task_input(
    message: Message, state: FSMContext, settings: Settings
) -> None:
    """Handle text input after /task with no args."""
    if not message.text:
        await message.answer("❌ Напиши текст задачи")
        return
    await state.clear()
    await _create_task(message, message.text.strip(), settings)


async def _create_task(message: Message, text: str, settings: Settings) -> None:
    """Create a Notion task and reply with confirmation."""
    if not settings.notion_token:
        await message.answer("❌ NOTION_TOKEN не настроен")
        return

    due_date = _extract_due_date(text)

    try:
        client = NotionClient(settings.notion_token)
        url = await client.create_task(text, due_date)
    except Exception as e:
        logger.exception("Failed to create Notion task")
        await message.answer(f"❌ Не удалось создать задачу: {e}")
        return

    due_info = f"\n📅 Срок: <b>{due_date}</b>" if due_date else ""
    await message.answer(
        f"✅ Задача добавлена в Notion\n\n"
        f"📝 <b>{text}</b>"
        f"{due_info}"
    )
    logger.info("Notion task created: %s (due: %s)", text, due_date)
