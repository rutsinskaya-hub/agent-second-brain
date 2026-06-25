"""Briefing command — re-run the morning briefing on demand (with fresh data)."""

import asyncio
import logging
from pathlib import Path

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from d_brain.config import Settings

router = Router(name="briefing")
logger = logging.getLogger(__name__)

_TIMEOUT = 180  # the script runs Claude; ~30s typical, allow headroom


@router.message(Command("briefing"))
async def cmd_briefing(message: Message, settings: Settings) -> None:
    """Re-send the morning briefing now.

    Reuses scripts/briefing.sh — the same script the 09:00 timer runs. It
    gathers fresh tasks/calendar/mail, formats via Claude, and sends the
    briefing to Telegram itself, so here we only launch it and tidy up.
    """
    user_id = message.from_user.id if message.from_user else "unknown"
    logger.info("Briefing command triggered by user %s", user_id)

    script = Path(settings.vault_path).parent / "scripts" / "briefing.sh"
    if not script.exists():
        await message.answer("❌ Скрипт брифинга не найден")
        return

    status = await message.answer("⏳ Собираю свежий брифинг...")
    try:
        proc = await asyncio.create_subprocess_exec(
            "/bin/bash", str(script),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=_TIMEOUT)
    except asyncio.TimeoutError:
        await status.edit_text("❌ Брифинг не успел собраться за 3 минуты")
        return
    except Exception as e:
        logger.exception("Briefing command failed")
        await status.edit_text(f"❌ Ошибка: {e}")
        return

    # The script delivers the briefing itself. On success just clear the status.
    if proc.returncode == 0:
        try:
            await status.delete()
        except Exception:
            pass
    else:
        logger.error("Briefing script exited %s: %s", proc.returncode,
                     (out or b"").decode("utf-8", "replace")[-400:])
        await status.edit_text("❌ Брифинг завершился с ошибкой, см. логи")
