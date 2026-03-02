"""Reply keyboards for Telegram bot."""

from aiogram.types import ReplyKeyboardMarkup
from aiogram.utils.keyboard import ReplyKeyboardBuilder


def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Main reply keyboard with common commands."""
    builder = ReplyKeyboardBuilder()
    # First row: main commands
    builder.button(text="📊 Статус")
    builder.button(text="⚙️ Обработать")
    builder.button(text="📅 Неделя")
    # Second row: additional
    builder.button(text="📧 Почта")
    builder.button(text="✨ Запрос")
    builder.button(text="❓ Помощь")
    builder.adjust(3, 3)  # 3 in first row, 3 in second
    return builder.as_markup(resize_keyboard=True, is_persistent=True)
