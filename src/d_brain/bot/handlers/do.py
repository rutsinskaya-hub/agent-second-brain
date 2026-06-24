"""Handler for /do command - arbitrary Claude requests with streaming."""

import logging
from datetime import date
from pathlib import Path

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from d_brain.bot.states import DoCommandState
from d_brain.config import Settings
from d_brain.services.streaming import StreamEvent, stream_claude
from d_brain.services.transcription import DeepgramTranscriber

router = Router(name="do")
logger = logging.getLogger(__name__)


@router.message(Command("do"))
async def cmd_do(message: Message, command: CommandObject, state: FSMContext, settings: Settings) -> None:
    """Handle /do command."""
    user_id = message.from_user.id if message.from_user else 0

    if command.args:
        await process_request_streaming(message, command.args, settings)
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

    await process_request_streaming(message, prompt, settings)


def _progress_label(tool_name: str) -> str:
    """Map a raw tool name to a human-friendly progress line.

    Returns "" for internal steps that should not be shown to the user.
    """
    name = tool_name.lower()
    # Internal plumbing — hide from the user
    if "toolsearch" in name:
        return ""
    if "notion" in name:
        if "query" in name:
            return "🔍 Ищу задачу в Notion..."
        if "patch" in name or "update" in name:
            return "✏️ Обновляю задачу..."
        if "post-page" in name or "create" in name:
            return "➕ Создаю задачу..."
        return "📋 Работаю с Notion..."
    if name in ("read", "glob", "grep"):
        return "🔍 Ищу..."
    if name in ("write", "edit"):
        return "✏️ Записываю..."
    if name == "bash":
        return "⚙️ Выполняю..."
    return "⏳ Работаю..."


async def process_request_streaming(
    message: Message,
    prompt: str,
    settings: Settings,
) -> None:
    """Process request with Claude streaming — show tool calls in real-time."""
    today = date.today()
    vault_path = Path(settings.vault_path)
    mcp_config = (vault_path.parent / "mcp-config.json").resolve()

    full_prompt = f"""Ты - персональный ассистент d-brain.

CONTEXT:
- Текущая дата: {today}
- Vault path: {vault_path}

MCP TOOLS:
- Для задач используй Notion: mcp__notion__API-post-database-query (database_id: "305289eb-342c-80ec-856d-f1c014cdff68")
- Для создания задач: mcp__notion__API-post-page

USER REQUEST:
{prompt}

CRITICAL OUTPUT FORMAT:
- Return ONLY raw HTML for Telegram (parse_mode=HTML)
- NO markdown: no **, no ##, no ```, no tables
- Allowed tags: <b>, <i>, <code>, <s>, <u>
- Be concise - Telegram has 4096 char limit"""

    status_msg = await message.answer("⏳ Работаю...")
    last_status = "⏳ Работаю..."

    try:
        async for event in stream_claude(
            prompt=full_prompt,
            cwd=vault_path.parent,
            mcp_config=mcp_config if mcp_config.exists() else None,
            notion_token=settings.notion_token,
        ):
            if event.kind == "tool_call":
                # Update the single status message with a friendly progress
                # label instead of spamming a new message per tool call.
                # Internal steps (e.g. ToolSearch) are hidden entirely.
                label = _progress_label(event.tool_name)
                if label and label != last_status:
                    last_status = label
                    try:
                        await status_msg.edit_text(label)
                    except Exception:
                        pass

            elif event.kind == "done":
                # Delete the status message
                try:
                    await status_msg.delete()
                except Exception:
                    pass

                # Send final result
                final_text = event.text.strip()
                if not final_text:
                    final_text = "✓ Выполнено"

                # Add cost info
                if event.duration_ms > 0:
                    secs = event.duration_ms / 1000
                    final_text += f"\n\n<i>⏱ {secs:.1f}s</i>"

                try:
                    await message.answer(final_text)
                except Exception:
                    await message.answer(final_text, parse_mode=None)

            elif event.kind == "error":
                try:
                    await status_msg.edit_text(f"❌ {event.text}")
                except Exception:
                    await message.answer(f"❌ {event.text}")

    except Exception as e:
        logger.exception("Streaming error")
        try:
            await status_msg.edit_text(f"❌ Ошибка: {e}")
        except Exception:
            await message.answer(f"❌ Ошибка: {e}")
