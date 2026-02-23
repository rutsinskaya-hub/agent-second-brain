"""Photo message handler."""

import logging
from datetime import datetime

from aiogram import Bot, Router
from aiogram.types import Message

from d_brain.config import Settings
from d_brain.services.session import SessionStore
from d_brain.services.storage import VaultStorage

router = Router(name="photo")
logger = logging.getLogger(__name__)


@router.message(lambda m: m.photo is not None)
async def handle_photo(message: Message, bot: Bot, settings: Settings) -> None:
    """Handle photo messages."""
    if not message.photo or not message.from_user:
        return

    storage = VaultStorage(settings.vault_path)

    # Get largest photo
    photo = message.photo[-1]

    try:
        file = await bot.get_file(photo.file_id)
        if not file.file_path:
            await message.answer("❌ Не удалось скачать фото")
            return

        file_bytes = await bot.download_file(file.file_path)
        if not file_bytes:
            await message.answer("❌ Не удалось скачать фото")
            return

        timestamp = datetime.fromtimestamp(message.date.timestamp())
        photo_bytes = file_bytes.read()

        extension = "jpg"
        if file.file_path and "." in file.file_path:
            extension = file.file_path.rsplit(".", 1)[-1]

        relative_path = storage.save_attachment(
            photo_bytes,
            timestamp.date(),
            timestamp,
            extension,
        )

        content = f"![[{relative_path}]]"
        if message.caption:
            content += f"\n\n{message.caption}"

        storage.append_to_daily(content, timestamp, "[photo]")

        session = SessionStore(settings.vault_path)
        session.append(
            message.from_user.id,
            "photo",
            path=relative_path,
            caption=message.caption,
            msg_id=message.message_id,
        )

        await message.answer("📷 ✓ Сохранено")
        logger.info("Photo saved: %s", relative_path)

    except Exception as e:
        logger.exception("Error processing photo")
        await message.answer(f"❌ Ошибка: {e}")
