"""Email handler — check Gmail and analyze with Claude."""

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from d_brain.bot.utils import run_with_progress
from d_brain.config import Settings
from d_brain.services.gmail import GmailClient
from d_brain.services.processor import ClaudeProcessor

router = Router(name="email")
logger = logging.getLogger(__name__)


@router.message(Command("email"))
async def cmd_email(message: Message, settings: Settings) -> None:
    """Handle /email command — fetch and analyze Gmail."""
    await check_email_intent(message, settings)


async def check_email_intent(message: Message, settings: Settings) -> None:
    """Shared logic for /email command, button, and voice/text intent."""
    if not settings.gmail_enabled:
        await message.answer("📧 Gmail не настроен. Запусти OAuth: <code>python -m d_brain.services.gmail --setup</code>")
        return

    status_msg = await message.answer("📧 Загружаю почту...")

    client = GmailClient(settings.gmail_credentials_path, settings.gmail_token_path)

    try:
        emails = client.fetch_emails(hours=24, unread_only=True, max_results=20)
    except Exception as e:
        logger.exception("Gmail fetch failed")
        await status_msg.edit_text(f"❌ Ошибка Gmail: {e}")
        return

    if not emails:
        await status_msg.edit_text("📧 Новых писем нет.")
        return

    # Show quick preview while Claude analyzes
    preview = client.format_summary_html(emails)
    await status_msg.edit_text(f"{preview}\n\n⏳ Анализирую...")

    # Format for Claude and run analysis
    email_data = client.format_for_claude(emails)
    processor = ClaudeProcessor(settings.vault_path, settings.notion_token)

    result = await run_with_progress(
        status_msg,
        "Анализирую почту...",
        lambda: processor.analyze_emails(email_data),
    )

    if "error" in result:
        await status_msg.edit_text(f"{preview}\n\n❌ {result['error']}")
    else:
        report = result.get("report", "✓ Анализ завершён")
        try:
            await status_msg.edit_text(report)
        except Exception:
            await status_msg.edit_text(report, parse_mode=None)

    logger.info("Email check complete: %d emails fetched", len(emails))
