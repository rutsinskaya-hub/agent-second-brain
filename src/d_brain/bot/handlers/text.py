"""Text message handler."""

import logging
from datetime import datetime

from aiogram import Router
from aiogram.types import Message

from d_brain.bot.utils import run_with_progress
from d_brain.config import Settings
from d_brain.services.intent import Intent, classify, classify_query, extract_due_date, extract_project, extract_query_project, extract_task_name
from d_brain.services.notion import NotionClient, _format_tasks_reply
from d_brain.services.processor import ClaudeProcessor
from d_brain.services.session import SessionStore
from d_brain.services.storage import VaultStorage

router = Router(name="text")
logger = logging.getLogger(__name__)


@router.message(lambda m: m.text is not None and not m.text.startswith("/"))
async def handle_text(message: Message, settings: Settings) -> None:
    """Handle text messages with intent routing."""
    if not message.text or not message.from_user:
        return

    text = message.text
    storage = VaultStorage(settings.vault_path)
    timestamp = datetime.fromtimestamp(message.date.timestamp())
    user_id = message.from_user.id
    session = SessionStore(settings.vault_path)

    # ── Intent routing ────────────────────────────────────────────────────
    intent = classify(text) if settings.notion_token else Intent.SAVE

    if intent == Intent.CREATE_TASK:
        task_name = extract_task_name(text)
        project, task_name = extract_project(task_name)
        due_date = extract_due_date(text)

        try:
            client = NotionClient(settings.notion_token)
            await client.create_task(task_name, due_date, project)
        except Exception as e:
            logger.exception("Failed to create Notion task from text")
            await message.answer(f"❌ Не удалось создать задачу: {e}")
            return

        project_info = f"\n📁 Проект: <b>{project}</b>" if project else ""
        due_info = f"\n📅 Срок: <b>{due_date}</b>" if due_date else ""
        await message.answer(
            f"✅ Задача добавлена в Notion\n"
            f"📝 <b>{task_name}</b>{project_info}{due_info}"
        )
        storage.append_to_daily(text, timestamp, "[text][task]")
        session.append(user_id, "text", text=text, msg_id=message.message_id)
        logger.info("Notion task created from text: %s (project: %s)", task_name, project)

    elif intent == Intent.QUERY_TASKS:
        query_type = classify_query(text)
        project = extract_query_project(text)
        try:
            client = NotionClient(settings.notion_token)
            tasks = await client.query_tasks(query_type.value, project=project)
        except Exception as e:
            logger.exception("Failed to query Notion tasks")
            await message.answer(f"❌ Не удалось получить задачи: {e}")
            return
        await message.answer(_format_tasks_reply(tasks, query_type.value, project=project))
        storage.append_to_daily(text, timestamp, "[text][query]")
        session.append(user_id, "text", text=text, msg_id=message.message_id)

    elif intent == Intent.CHECK_EMAIL:
        from d_brain.bot.handlers.email import check_email_intent
        await check_email_intent(message, settings)
        storage.append_to_daily(text, timestamp, "[text][email]")
        session.append(user_id, "text", text=text, msg_id=message.message_id)

    elif intent == Intent.NOTION_ACTION:
        status_msg = await message.answer("⏳ Выполняю...")
        processor = ClaudeProcessor(settings.vault_path, settings.notion_token)

        result = await run_with_progress(
            status_msg,
            "Выполняю...",
            lambda: processor.execute_prompt(text, user_id),
        )

        if "error" in result:
            await status_msg.edit_text(f"❌ {result['error']}")
        else:
            report = result.get("report", "✓ Выполнено")
            try:
                await status_msg.edit_text(report)
            except Exception:
                await status_msg.edit_text(report, parse_mode=None)

        storage.append_to_daily(text, timestamp, "[text][action]")
        session.append(user_id, "text", text=text, msg_id=message.message_id)

    else:
        # Default: save to vault
        storage.append_to_daily(text, timestamp, "[text]")
        session.append(user_id, "text", text=text, msg_id=message.message_id)
        await message.answer("✓ Сохранено")
        logger.info("Text saved: %d chars", len(text))
