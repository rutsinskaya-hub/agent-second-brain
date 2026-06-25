"""Command handlers for /start, /help, /status."""

from datetime import date

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from d_brain.bot.keyboards import get_main_keyboard
from d_brain.config import Settings
from d_brain.services.session import SessionStore
from d_brain.services.storage import VaultStorage

router = Router(name="commands")


@router.message(Command("start"))
async def cmd_start(message: Message, settings: Settings) -> None:
    """Handle /start command."""
    cmds = [
        "/briefing — прислать утренний брифинг сейчас",
        "/task — добавить задачу в Notion",
        "/do — поручить ассистенту любой запрос",
        "/status — что записано сегодня",
        "/reminders — активные напоминания",
        "/weekly — недельный дайджест",
    ]
    if settings.gmail_enabled:
        cmds.append("/email — проверить почту")
    if settings.calendar_enabled:
        cmds.append("/calendar — расписание на сегодня")
    cmds.append("/help — подробнее")
    await message.answer(
        "<b>d-brain</b> — твой голосовой второй мозг\n\n"
        "Говори или пиши обычными словами — я пойму и сделаю:\n"
        "• «добавь задачу позвонить юристу завтра»\n"
        "• «перенеси налоги на 25 июля»\n"
        "• «отметь задачу про лендинг сделанной»\n"
        "• «покажи задачи на сегодня»\n"
        "• «напомни забрать визитки в 18:00»\n\n"
        "Задачи живут в Notion. Мысли и заметки сохраняю в дневник.\n\n"
        "<b>Команды:</b>\n" + "\n".join(cmds),
        reply_markup=get_main_keyboard(),
    )


@router.message(Command("help"))
async def cmd_help(message: Message, settings: Settings) -> None:
    """Handle /help command."""
    extra = ""
    if settings.gmail_enabled:
        extra += "/email — проверить почту\n"
    if settings.calendar_enabled:
        extra += "/calendar — расписание на сегодня\n"
    await message.answer(
        "<b>Что я умею</b>\n\n"
        "<b>Управляй задачами обычными словами</b> — голосом или текстом:\n"
        "• добавить, перенести срок, отметить выполненной, показать задачи\n"
        "• поставить напоминание\n"
        "Разберу формулировку и сделаю в Notion. Необычную фразу пойму через Claude.\n\n"
        "<b>Что сохраняю в дневник:</b>\n"
        "🎤 голос (транскрибирую) · 💬 текст · 📷 фото · ↩️ пересланное\n\n"
        "<b>Команды:</b>\n"
        "/briefing — прислать утренний брифинг сейчас\n"
        "/task — быстро добавить задачу\n"
        "/do — произвольный запрос к ассистенту\n"
        "/status — сколько записей сегодня\n"
        "/reminders — активные напоминания\n"
        "/weekly — недельный дайджест\n"
        "/process — разобрать записи дня\n"
        + extra +
        "\n<i>Пример: /task Позвонить Петру завтра</i>\n"
        "<i>Или просто: «перенеси просроченные задачи на понедельник»</i>"
    )


@router.message(Command("status"))
async def cmd_status(message: Message, settings: Settings) -> None:
    """Handle /status command."""
    user_id = message.from_user.id if message.from_user else 0
    storage = VaultStorage(settings.vault_path)

    session = SessionStore(settings.vault_path)
    session.append(user_id, "command", cmd="/status")

    today = date.today()
    content = storage.read_daily(today)

    if not content:
        await message.answer(f"📅 <b>{today}</b>\n\nЗаписей пока нет.")
        return

    lines = content.strip().split("\n")
    entries = [line for line in lines if line.startswith("## ")]

    voice_count = sum(1 for e in entries if "[voice]" in e)
    text_count = sum(1 for e in entries if "[text]" in e)
    photo_count = sum(1 for e in entries if "[photo]" in e)
    forward_count = sum(1 for e in entries if "[forward from:" in e)

    total = len(entries)

    week_stats = ""
    stats = session.get_stats(user_id, days=7)
    if stats:
        week_stats = "\n\n<b>За 7 дней:</b>"
        for entry_type, count in sorted(stats.items()):
            week_stats += f"\n• {entry_type}: {count}"

    await message.answer(
        f"📅 <b>{today}</b>\n\n"
        f"Всего записей: <b>{total}</b>\n"
        f"- 🎤 Голосовых: {voice_count}\n"
        f"- 💬 Текстовых: {text_count}\n"
        f"- 📷 Фото: {photo_count}\n"
        f"- ↩️ Пересланных: {forward_count}"
        f"{week_stats}"
    )
