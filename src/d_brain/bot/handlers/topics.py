"""Forum Topics handler — route messages by topic with streaming.

Works in groups with Forum Topics enabled.
Each topic can have its own system prompt, cwd, and MCP config.
Commands:
  /topic_setup <name> — configure current topic
  /topic_prompt <text> — set system prompt for current topic
  /topics — list configured topics
"""

import logging
from datetime import date
from pathlib import Path

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from d_brain.config import Settings
from d_brain.services.streaming import stream_claude
from d_brain.services.topics import TopicConfig, TopicManager
from d_brain.services.transcription import DeepgramTranscriber

router = Router(name="topics")
logger = logging.getLogger(__name__)

# Global topic manager — set from main.py
topic_manager: TopicManager | None = None


@router.message(Command("topics"))
async def cmd_topics(message: Message) -> None:
    """List configured topics."""
    if not topic_manager:
        await message.answer("Topics не настроены.")
        return

    topics = topic_manager.list_all()
    if not topics:
        await message.answer("📋 Нет настроенных топиков.\n\nИспользуй /topic_setup <имя> в нужном топике.")
        return

    lines = [f"📋 <b>Топики ({len(topics)})</b>\n"]
    for t in topics:
        status = "✅" if t.enabled else "❌"
        lines.append(f"{status} <b>{t.name}</b> (id: {t.topic_id})")
        if t.prompt != TopicConfig.prompt:
            lines.append(f"   📝 Кастомный промпт")
        if t.cwd:
            lines.append(f"   📁 {t.cwd}")
    await message.answer("\n".join(lines))


@router.message(Command("topic_setup"))
async def cmd_topic_setup(message: Message, command: CommandObject) -> None:
    """Configure current topic."""
    if not topic_manager:
        await message.answer("Topics не настроены.")
        return

    topic_id = message.message_thread_id
    if not topic_id:
        await message.answer("❌ Эта команда работает только в топике (ветке).")
        return

    name = command.args or f"Topic {topic_id}"
    config = topic_manager.get(topic_id) or TopicConfig(topic_id=topic_id, name=name)
    config.name = name
    topic_manager.add(config)

    await message.answer(
        f"✅ Топик настроен\n\n"
        f"📝 <b>{name}</b>\n"
        f"🆔 {topic_id}\n\n"
        f"Команды:\n"
        f"/topic_prompt <текст> — задать системный промпт\n"
        f"/topic_cwd <путь> — задать рабочую директорию"
    )


@router.message(Command("topic_prompt"))
async def cmd_topic_prompt(message: Message, command: CommandObject) -> None:
    """Set system prompt for current topic."""
    if not topic_manager:
        return

    topic_id = message.message_thread_id
    if not topic_id:
        await message.answer("❌ Только в топике.")
        return

    if not command.args:
        await message.answer("❌ Укажи промпт: /topic_prompt Ты — финансовый аналитик...")
        return

    config = topic_manager.get(topic_id)
    if not config:
        config = TopicConfig(topic_id=topic_id, name=f"Topic {topic_id}")

    config.prompt = command.args
    topic_manager.add(config)
    await message.answer(f"✅ Промпт обновлен для <b>{config.name}</b>")


@router.message(Command("topic_cwd"))
async def cmd_topic_cwd(message: Message, command: CommandObject) -> None:
    """Set working directory for current topic."""
    if not topic_manager:
        return

    topic_id = message.message_thread_id
    if not topic_id:
        await message.answer("❌ Только в топике.")
        return

    if not command.args:
        await message.answer("❌ Укажи путь: /topic_cwd /home/myuser/projects/myproject")
        return

    config = topic_manager.get(topic_id)
    if not config:
        config = TopicConfig(topic_id=topic_id, name=f"Topic {topic_id}")

    config.cwd = command.args.strip()
    topic_manager.add(config)
    await message.answer(f"✅ Рабочая директория: <code>{config.cwd}</code>")


async def handle_topic_message(
    message: Message,
    bot: Bot,
    settings: Settings,
    text: str | None = None,
) -> None:
    """Handle a message in a forum topic.

    First tries intent routing (email, calendar, tasks, reminders),
    then falls back to streaming Claude for everything else.
    """
    if not topic_manager:
        return

    topic_id = message.message_thread_id

    config = topic_manager.get_or_default(topic_id)
    if not config.enabled:
        return

    # Get text from message or voice
    user_text = text
    if not user_text and message.text:
        user_text = message.text
    if not user_text and message.voice:
        transcriber = DeepgramTranscriber(settings.deepgram_api_key)
        try:
            file = await bot.get_file(message.voice.file_id)
            if file.file_path:
                file_bytes = await bot.download_file(file.file_path)
                if file_bytes:
                    audio_bytes = file_bytes.read()
                    user_text = await transcriber.transcribe(audio_bytes)
                    if user_text:
                        await message.answer(f"🎤 <i>{user_text}</i>")
        except Exception:
            logger.exception("Voice transcription failed in topic")

    if not user_text:
        return

    # ── Intent routing (same as private chat) ──────────────────────────
    from d_brain.services.intent import Intent, classify

    intent = classify(user_text) if settings.notion_token else Intent.SAVE

    if intent == Intent.SET_REMINDER:
        from d_brain.bot.handlers.reminder import set_reminder_intent
        await set_reminder_intent(message, settings, user_text)
        return

    if intent == Intent.CREATE_TASK:
        from d_brain.services.intent import extract_due_date, extract_project, extract_task_name
        from d_brain.services.notion import NotionClient
        task_name = extract_task_name(user_text)
        project, task_name = extract_project(task_name)
        due_date = extract_due_date(user_text)
        try:
            client = NotionClient(settings.notion_token)
            await client.create_task(task_name, due_date, project)
            project_info = f"\n📁 Проект: <b>{project}</b>" if project else ""
            due_info = f"\n📅 Срок: <b>{due_date}</b>" if due_date else ""
            await message.answer(f"✅ Задача добавлена\n📝 <b>{task_name}</b>{project_info}{due_info}")
        except Exception as e:
            await message.answer(f"❌ {e}")
        return

    if intent == Intent.QUERY_TASKS:
        from d_brain.services.intent import classify_query, extract_query_project
        from d_brain.services.notion import NotionClient, _format_tasks_reply
        query_type = classify_query(user_text)
        project = extract_query_project(user_text)
        try:
            client = NotionClient(settings.notion_token)
            tasks = await client.query_tasks(query_type.value, project=project)
            await message.answer(_format_tasks_reply(tasks, query_type.value, project=project))
        except Exception as e:
            await message.answer(f"❌ {e}")
        return

    if intent == Intent.CHECK_EMAIL:
        from d_brain.bot.handlers.email import check_email_intent
        await check_email_intent(message, settings)
        return

    if intent == Intent.MANAGE_EMAIL:
        from d_brain.bot.handlers.email import manage_email_intent
        await manage_email_intent(message, settings, user_text)
        return

    if intent == Intent.CHECK_CALENDAR:
        from d_brain.bot.handlers.calendar import check_calendar_intent
        await check_calendar_intent(message, settings, user_text)
        return

    if intent == Intent.CREATE_EVENT:
        from d_brain.bot.handlers.calendar import create_event_intent
        await create_event_intent(message, settings, user_text)
        return

    # ── Fallback: streaming Claude with topic config ───────────────────
    vault_path = Path(settings.vault_path)
    default_cwd = str(vault_path.parent)
    default_mcp = str((vault_path.parent / "mcp-config.json").resolve())

    cwd = config.cwd or default_cwd
    mcp = config.mcp_config or default_mcp
    today = date.today()

    full_prompt = f"""{config.prompt}

CONTEXT:
- Дата: {today}

MCP TOOLS:
- Notion задачи: mcp__notion__API-post-database-query (database_id: "305289eb-342c-80ec-856d-f1c014cdff68")
- Notion создание: mcp__notion__API-post-page

ЗАПРОС:
{user_text}

OUTPUT: HTML для Telegram. Теги: <b>, <i>, <code>. Без markdown. Лимит 4096."""

    status_msg = await message.answer("⏳ Думаю...")

    try:
        async for event in stream_claude(
            prompt=full_prompt,
            cwd=cwd,
            mcp_config=mcp if Path(mcp).exists() else None,
            notion_token=settings.notion_token,
        ):
            if event.kind == "tool_call":
                try:
                    await message.answer(event.tool_input)
                except Exception:
                    pass

            elif event.kind == "done":
                try:
                    await status_msg.delete()
                except Exception:
                    pass

                final = event.text.strip() or "✓"
                if event.duration_ms > 0:
                    final += f"\n\n<i>⏱ {event.duration_ms / 1000:.1f}s</i>"
                try:
                    await message.answer(final)
                except Exception:
                    await message.answer(final, parse_mode=None)

            elif event.kind == "error":
                try:
                    await status_msg.edit_text(f"❌ {event.text}")
                except Exception:
                    pass

    except Exception as e:
        logger.exception("Topic streaming error")
        try:
            await status_msg.edit_text(f"❌ {e}")
        except Exception:
            pass
