"""Чеклист ежедневных ритуалов: /habits и нажатия по кнопкам."""

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from d_brain.config import Settings
from d_brain.services.habits import BY_KEY, HabitStore, render_checklist

logger = logging.getLogger(__name__)

router = Router(name="habits")


def _store(settings: Settings) -> HabitStore:
    return HabitStore(settings.vault_path / "habits.json")


def _markup(rows: list[list[dict[str, str]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(**btn) for btn in row] for row in rows]
    )


@router.message(Command("habits"))
async def cmd_habits(message: Message, settings: Settings) -> None:
    """Показать чеклист ритуалов на сегодня."""
    text, rows = render_checklist(_store(settings))
    await message.answer(text, reply_markup=_markup(rows))


@router.callback_query(F.data.startswith("hab:"))
async def cb_habit(callback: CallbackQuery, settings: Settings) -> None:
    """Переключить ритуал и перерисовать сообщение на месте."""
    key = (callback.data or "").split(":", 1)[1]
    if key not in BY_KEY:
        await callback.answer("Неизвестный ритуал")
        return

    store = _store(settings)
    now_done = store.toggle(key)
    title = BY_KEY[key]["title"]
    streak = store.streak(key)

    if now_done:
        note = f"{title}: отмечено"
        if streak > 1:
            note += f", {streak} дн. подряд"
    else:
        note = f"{title}: снято"
    await callback.answer(note)

    text, rows = render_checklist(store)
    try:
        if callback.message:
            await callback.message.edit_text(text, reply_markup=_markup(rows))
    except Exception as e:
        # Telegram ругается, если текст не изменился — это не ошибка для нас.
        if "message is not modified" not in str(e):
            logger.warning("Не удалось перерисовать чеклист: %s", e)
