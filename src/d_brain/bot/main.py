"""Telegram bot initialization and polling."""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, Update

from d_brain.config import Settings

logger = logging.getLogger(__name__)


def create_bot(settings: Settings) -> Bot:
    """Create and configure the Telegram bot."""
    return Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def create_dispatcher() -> Dispatcher:
    """Create and configure the dispatcher with routers."""
    from d_brain.bot.handlers import briefing, buttons, calendar, commands, do, email, forward, habits, photo, process, reminder, task, text, topics, voice, weekly

    # Use memory storage for FSM (required for /do and /task command states)
    dp = Dispatcher(storage=MemoryStorage())

    # Register routers - ORDER MATTERS
    dp.include_router(commands.router)
    dp.include_router(briefing.router)  # /briefing command
    dp.include_router(process.router)
    dp.include_router(weekly.router)
    dp.include_router(task.router)   # Before do/text to catch TaskCommandState
    dp.include_router(email.router)  # /email command
    dp.include_router(calendar.router)  # /calendar command
    dp.include_router(reminder.router)  # /reminders command
    dp.include_router(topics.router)    # /topics, /topic_setup commands
    dp.include_router(habits.router)    # /habits + нажатия hab:* по чеклисту ритуалов
    dp.include_router(do.router)     # Before voice/text to catch DoCommandState
    dp.include_router(buttons.router)  # Reply keyboard buttons
    dp.include_router(voice.router)
    dp.include_router(photo.router)
    dp.include_router(forward.router)
    dp.include_router(text.router)  # Must be last (catch-all for text)
    return dp


MiddlewareHandler = Callable[[Update, dict[str, Any]], Awaitable[Any]]
MiddlewareType = Callable[[MiddlewareHandler, Update, dict[str, Any]], Awaitable[Any]]


def create_auth_middleware(settings: Settings) -> MiddlewareType:
    """Create middleware to check user authorization."""

    async def auth_middleware(
        handler: Callable[[Update, dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: dict[str, Any],
    ) -> Any:
        # If explicitly allowed all users, just bypass check
        if settings.allow_all_users:
            return await handler(event, data)

        user = None
        if event.message:
            user = event.message.from_user
        elif event.callback_query:
            user = event.callback_query.from_user

        # If no users allowed and not allow_all_users -> deny everyone
        if not settings.allowed_user_ids:
            logger.warning("Access denied: no allowed_user_ids configured and allow_all_users is False")
            return None

        # Check if user is in allowed list
        if user and user.id not in settings.allowed_user_ids:
            logger.warning("Unauthorized access attempt from user %s", user.id)
            return None

        return await handler(event, data)

    return auth_middleware


async def run_bot(settings: Settings) -> None:
    """Run the bot with polling."""
    from pathlib import Path

    from d_brain.bot.handlers import reminder as reminder_handler
    from d_brain.bot.handlers import topics as topics_handler
    from d_brain.services.reminders import ReminderScheduler
    from d_brain.services.topics import TopicManager

    bot = create_bot(settings)
    dp = create_dispatcher()

    # Inject settings into all handlers via aiogram DI
    dp["settings"] = settings

    # Always add auth middleware for security (it handles allow_all_users internally)
    dp.update.middleware(create_auth_middleware(settings))

    # Initialize reminder scheduler
    reminders_path = Path(settings.vault_path) / "reminders.json"
    sched = ReminderScheduler(reminders_path)

    async def send_reminder(chat_id: int, text: str) -> None:
        await bot.send_message(chat_id, f"⏰ <b>Напоминание</b>\n\n{text}")

    sched.set_callback(send_reminder)
    count = sched.start_all()
    reminder_handler.scheduler = sched
    logger.info("Reminder scheduler started with %d active reminders", count)

    # Initialize topic manager for Forum Topics
    topics_path = Path(settings.vault_path) / "topics.json"
    topic_mgr = TopicManager(topics_path)
    topics_handler.topic_manager = topic_mgr
    logger.info("Topic manager loaded with %d topics", len(topic_mgr.list_all()))

    # Register bot command menu visible in Telegram UI.
    # Built dynamically so it reflects what is actually wired up: email and
    # calendar appear only when their Google tokens exist.
    commands = [
        BotCommand(command="briefing",  description="Прислать утренний брифинг сейчас"),
        BotCommand(command="task",      description="Добавить задачу в Notion"),
        BotCommand(command="do",        description="Поручить ассистенту любой запрос"),
        BotCommand(command="status",    description="Что записано сегодня"),
        BotCommand(command="habits",    description="Чеклист ежедневных ритуалов"),
        BotCommand(command="reminders", description="Активные напоминания"),
        BotCommand(command="weekly",    description="Недельный дайджест из заметок"),
        BotCommand(command="process",   description="Разобрать записи дня"),
    ]
    if settings.anko_mail_enabled or settings.gmail_enabled:
        commands.append(BotCommand(command="email", description="Проверить почту"))
    if settings.calendar_enabled:
        commands.append(BotCommand(command="calendar", description="Расписание на сегодня"))
    commands.append(BotCommand(command="help", description="Что я умею"))
    await bot.set_my_commands(commands)
    logger.info("Bot commands registered: %d (anko_mail=%s, gmail=%s, calendar=%s)",
                len(commands), settings.anko_mail_enabled, settings.gmail_enabled,
                settings.calendar_enabled)

    logger.info("Starting bot polling...")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()
