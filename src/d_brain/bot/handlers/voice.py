"""Voice message handler."""

import logging
from datetime import datetime

from aiogram import Bot, Router
from aiogram.types import Message

from d_brain.bot.utils import run_with_progress
from d_brain.config import Settings
from d_brain.services.intent import Intent, classify, classify_query, extract_due_date, extract_project, extract_query_project, extract_task_name
from d_brain.services.notion import NotionClient, _format_tasks_reply
from d_brain.services.processor import ClaudeProcessor
from d_brain.services.session import SessionStore
from d_brain.services.storage import VaultStorage
from d_brain.services.transcription import DeepgramTranscriber

router = Router(name="voice")
logger = logging.getLogger(__name__)


@router.message(lambda m: m.voice is not None)
async def handle_voice(message: Message, bot: Bot, settings: Settings) -> None:
    """Handle voice messages with intent routing."""
    if not message.voice or not message.from_user:
        return

    await message.chat.do(action="typing")

    storage = VaultStorage(settings.vault_path)
    transcriber = DeepgramTranscriber(settings.deepgram_api_key)

    try:
        file = await bot.get_file(message.voice.file_id)
        if not file.file_path:
            await message.answer("❌ Не удалось скачать голосовое")
            return

        file_bytes = await bot.download_file(file.file_path)
        if not file_bytes:
            await message.answer("❌ Не удалось скачать голосовое")
            return

        audio_bytes = file_bytes.read()
        transcript = await transcriber.transcribe(audio_bytes)

        if not transcript:
            await message.answer("❌ Не удалось распознать речь")
            return

        timestamp = datetime.fromtimestamp(message.date.timestamp())
        user_id = message.from_user.id

        session = SessionStore(settings.vault_path)

        # ── Intent routing ────────────────────────────────────────────────
        intent = classify(transcript) if settings.notion_token else Intent.SAVE

        if intent == Intent.CREATE_TASK:
            await _handle_create_task(message, transcript, timestamp, storage, session, user_id, settings)

        elif intent == Intent.QUERY_TASKS:
            await _handle_query_tasks(message, transcript, timestamp, storage, session, user_id, settings)

        elif intent == Intent.CHECK_EMAIL:
            from d_brain.bot.handlers.email import check_email_intent
            await check_email_intent(message, settings)
            storage.append_to_daily(transcript, timestamp, "[voice][email]")
            session.append(user_id, "voice", text=transcript, msg_id=message.message_id)

        elif intent == Intent.NOTION_ACTION:
            await _handle_notion_action(message, transcript, timestamp, storage, session, user_id, settings)

        else:
            # Default: save to vault
            storage.append_to_daily(transcript, timestamp, "[voice]")
            session.append(user_id, "voice", text=transcript,
                           duration=message.voice.duration, msg_id=message.message_id)
            await message.answer(f"🎤 {transcript}\n\n✓ Сохранено")
            logger.info("Voice saved: %d chars", len(transcript))

    except Exception as e:
        logger.exception("Error processing voice message")
        await message.answer(f"❌ Ошибка: {e}")


async def _handle_create_task(
    message: Message,
    transcript: str,
    timestamp: datetime,
    storage: VaultStorage,
    session: SessionStore,
    user_id: int,
    settings: Settings,
) -> None:
    """Fast path: create Notion task directly."""
    task_name = extract_task_name(transcript)
    project, task_name = extract_project(task_name)
    due_date = extract_due_date(transcript)

    try:
        client = NotionClient(settings.notion_token)
        await client.create_task(task_name, due_date, project)
    except Exception as e:
        logger.exception("Failed to create Notion task from voice")
        await message.answer(f"🎤 <i>{transcript}</i>\n\n❌ Не удалось создать задачу: {e}")
        return

    project_info = f"\n📁 Проект: <b>{project}</b>" if project else ""
    due_info = f"\n📅 Срок: <b>{due_date}</b>" if due_date else ""
    await message.answer(
        f"🎤 <i>{transcript}</i>\n\n"
        f"✅ Задача добавлена в Notion\n"
        f"📝 <b>{task_name}</b>{project_info}{due_info}"
    )
    storage.append_to_daily(transcript, timestamp, "[voice][task]")
    session.append(user_id, "voice", text=transcript, msg_id=message.message_id)
    logger.info("Notion task created from voice: %s (project: %s, due: %s)", task_name, project, due_date)


async def _handle_query_tasks(
    message: Message,
    transcript: str,
    timestamp: datetime,
    storage: VaultStorage,
    session: SessionStore,
    user_id: int,
    settings: Settings,
) -> None:
    """Fast path: query Notion tasks directly."""
    query_type = classify_query(transcript)
    project = extract_query_project(transcript)

    try:
        client = NotionClient(settings.notion_token)
        tasks = await client.query_tasks(query_type.value, project=project)
    except Exception as e:
        logger.exception("Failed to query Notion tasks")
        await message.answer(f"🎤 <i>{transcript}</i>\n\n❌ Не удалось получить задачи: {e}")
        return

    reply = _format_tasks_reply(tasks, query_type.value, project=project)
    await message.answer(f"🎤 <i>{transcript}</i>\n\n{reply}")
    storage.append_to_daily(transcript, timestamp, "[voice][query]")
    session.append(user_id, "voice", text=transcript, msg_id=message.message_id)


async def _handle_notion_action(
    message: Message,
    transcript: str,
    timestamp: datetime,
    storage: VaultStorage,
    session: SessionStore,
    user_id: int,
    settings: Settings,
) -> None:
    """Slow path: delegate to Claude with Notion MCP."""
    status_msg = await message.answer(f"🎤 <i>{transcript}</i>\n\n⏳ Выполняю...")

    processor = ClaudeProcessor(settings.vault_path, settings.notion_token)

    result = await run_with_progress(
        status_msg,
        "Выполняю...",
        lambda: processor.execute_prompt(transcript, user_id),
    )

    if "error" in result:
        await status_msg.edit_text(
            f"🎤 <i>{transcript}</i>\n\n❌ {result['error']}"
        )
    else:
        report = result.get("report", "✓ Выполнено")
        try:
            await status_msg.edit_text(f"🎤 <i>{transcript}</i>\n\n{report}")
        except Exception:
            await status_msg.edit_text(f"🎤 <i>{transcript}</i>\n\n{report}", parse_mode=None)

    storage.append_to_daily(transcript, timestamp, "[voice][action]")
    session.append(user_id, "voice", text=transcript, msg_id=message.message_id)
    logger.info("Notion action from voice: %s", transcript[:60])
