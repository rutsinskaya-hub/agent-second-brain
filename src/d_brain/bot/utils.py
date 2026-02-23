"""Shared bot utilities."""

import asyncio
from collections.abc import Callable
from typing import Any

from aiogram.types import Message


async def run_with_progress(
    status_msg: Message,
    label: str,
    fn: Callable[[], Any],
) -> Any:
    """Run a blocking function in a thread, updating the status message every 30s.

    Args:
        status_msg: Message to edit with progress updates.
        label: Short description shown in the status (e.g. "Обрабатываю...").
        fn: Zero-argument callable wrapping the blocking work (use lambda/partial).

    Returns:
        Whatever fn() returns.
    """
    task = asyncio.create_task(asyncio.to_thread(fn))

    elapsed = 0
    while not task.done():
        await asyncio.sleep(30)
        elapsed += 30
        if not task.done():
            try:
                await status_msg.edit_text(
                    f"⏳ {label} ({elapsed // 60}m {elapsed % 60}s)"
                )
            except Exception:
                pass  # Ignore edit errors (e.g. message not modified)

    return await task
