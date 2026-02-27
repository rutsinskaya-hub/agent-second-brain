"""Handler for /task command — instant Notion task creation."""

import logging

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from d_brain.bot.states import TaskCommandState
from d_brain.config import Settings
from d_brain.services.intent import extract_due_date, extract_project
from d_brain.services.notion import NotionClient

router = Router(name="task")
logger = logging.getLogger(__name__)


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

    project, task_text = extract_project(text)
    due_date = extract_due_date(text)

    try:
        client = NotionClient(settings.notion_token)
        url = await client.create_task(task_text, due_date, project)
    except Exception as e:
        logger.exception("Failed to create Notion task")
        await message.answer(f"❌ Не удалось создать задачу: {e}")
        return

    project_info = f"\n📁 Проект: <b>{project}</b>" if project else ""
    due_info = f"\n📅 Срок: <b>{due_date}</b>" if due_date else ""
    await message.answer(
        f"✅ Задача добавлена в Notion\n\n"
        f"📝 <b>{task_text}</b>"
        f"{project_info}{due_info}"
    )
    logger.info("Notion task created: %s (project: %s, due: %s)", task_text, project, due_date)
