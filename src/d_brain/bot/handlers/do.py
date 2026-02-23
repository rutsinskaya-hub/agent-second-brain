"""Handler for /do command - arbitrary Claude requests."""

import logging

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from d_brain.bot.formatters import format_process_report
from d_brain.bot.states import DoCommandState
from d_brain.bot.utils import run_with_progress
from d_brain.config import Settings
from d_brain.services.processor import ClaudeProcessor
from d_brain.services.transcription import DeepgramTranscriber

router = Router(name="do")
logger = logging.getLogger(__name__)


@router.message(Command("do"))
async def cmd_do(message: Message, command: CommandObject, state: FSMContext, settings: Settings) -> None:
    """Handle /do command."""
    user_id = message.from_user.id if message.from_user else 0

    if command.args:
        await process_request(message, command.args, user_id, settings)
        return

    await state.set_state(DoCommandState.waiting_for_input)
    await message.answer(
        "🎯 <b>Что сделать?</b>\n\n"
        "Отправь голосовое или текстовое сообщение с запросом."
    )


@router.message(DoCommandState.waiting_for_input)
async def handle_do_input(message: Message, bot: Bot, state: FSMContext, settings: Settings) -> None:
    """Handle voice/text input after /do command."""
    await state.clear()

    prompt = None

    if message.voice:
        await message.chat.do(action="typing")
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
            prompt = await transcriber.transcribe(audio_bytes)
        except Exception as e:
            logger.exception("Failed to transcribe voice for /do")
            await message.answer(f"❌ Не удалось транскрибировать: {e}")
            return

        if not prompt:
            await message.answer("❌ Не удалось распознать речь")
            return

        await message.answer(f"🎤 <i>{prompt}</i>")

    elif message.text:
        prompt = message.text
    else:
        await message.answer("❌ Отправь текст или голосовое сообщение")
        return

    user_id = message.from_user.id if message.from_user else 0
    await process_request(message, prompt, user_id, settings)


async def process_request(
    message: Message,
    prompt: str,
    user_id: int = 0,
    settings: Settings | None = None,
) -> None:
    """Process the user's request with Claude."""
    if settings is None:
        from d_brain.config import get_settings
        settings = get_settings()

    status_msg = await message.answer("⏳ Выполняю...")

    processor = ClaudeProcessor(settings.vault_path, settings.todoist_api_key, settings.notion_token)

    report = await run_with_progress(
        status_msg,
        "Выполняю...",
        lambda: processor.execute_prompt(prompt, user_id),
    )

    formatted = format_process_report(report)
    try:
        await status_msg.edit_text(formatted)
    except Exception:
        await status_msg.edit_text(formatted, parse_mode=None)
