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


async def manage_email_intent(message: Message, settings: Settings, user_text: str) -> None:
    """Handle email management requests (delete, trash, etc.)."""
    if not settings.gmail_enabled:
        await message.answer("📧 Gmail не настроен.")
        return

    status_msg = await message.answer("🗑 Загружаю почту...")

    client = GmailClient(settings.gmail_credentials_path, settings.gmail_token_path)

    try:
        emails = client.fetch_emails(hours=72, unread_only=False, max_results=30)
    except Exception as e:
        logger.exception("Gmail fetch failed")
        await status_msg.edit_text(f"❌ Ошибка Gmail: {e}")
        return

    if not emails:
        await status_msg.edit_text("📧 Нет писем для обработки.")
        return

    await status_msg.edit_text(f"🗑 Найдено {len(emails)} писем, анализирую...")

    email_data = client.format_for_claude(emails)
    processor = ClaudeProcessor(settings.vault_path, settings.notion_token)

    result = await run_with_progress(
        status_msg,
        "Анализирую...",
        lambda: processor.manage_emails(user_text, email_data),
    )

    if "error" in result:
        await status_msg.edit_text(f"❌ {result['error']}")
        return

    report = result.get("report", "")

    # Parse TRASH_IDS from Claude response
    trash_ids: list[str] = []
    clean_report = report
    for line in report.split("\n"):
        stripped = line.strip()
        if stripped.startswith("TRASH_IDS:"):
            ids_str = stripped[len("TRASH_IDS:"):].strip()
            if ids_str and ids_str != "none":
                trash_ids = [mid.strip() for mid in ids_str.split(",") if mid.strip()]
            clean_report = report.replace(line, "").strip()
            break

    if trash_ids:
        # Match IDs against fetched emails to validate
        valid_ids = {e["id"] for e in emails}
        safe_ids = [mid for mid in trash_ids if mid in valid_ids]

        if safe_ids:
            counts = client.trash_messages(safe_ids)
            clean_report += f"\n\n🗑 Удалено: {counts['trashed']}"
            if counts["failed"]:
                clean_report += f" (ошибок: {counts['failed']})"
        else:
            clean_report += "\n\n⚠️ Не удалось сопоставить ID писем"

    try:
        await status_msg.edit_text(clean_report)
    except Exception:
        await status_msg.edit_text(clean_report, parse_mode=None)

    logger.info("Email management: %d trashed", len(trash_ids))
